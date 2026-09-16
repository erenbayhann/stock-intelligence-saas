from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.data_quality_alert import DataQualityAlert
from app.models.job_run import JobRun
from app.models.model_version import ModelVersion


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _login(client):
    password = get_settings().admin_password
    response = client.post("/api/v1/admin/login", json={"password": password})
    assert response.status_code == 200
    return response


def _make_model_version(db_session, label, status):
    mv = ModelVersion(
        version_label=label, algorithm="random_forest", feature_set="price_fundamentals_macro",
        trained_at=datetime.now(timezone.utc), status=status, hyperparameters={},
        metrics={"test": {"mean_rank_ic": 0.01}},
    )
    db_session.add(mv)
    db_session.flush()
    return mv


def test_admin_routes_reject_missing_cookie(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/admin/jobs")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


def test_admin_login_rejects_wrong_password(db_session):
    client = _client(db_session)
    try:
        response = client.post("/api/v1/admin/login", json={"password": "definitely-not-it"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


def test_admin_login_sets_cookie_and_unlocks_protected_routes(db_session):
    client = _client(db_session)
    try:
        _login(client)
        response = client.get("/api/v1/admin/jobs")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "jobs" in response.json()


def test_admin_login_cookie_is_cross_site_capable_in_production():
    # Regression test: frontend and backend live on separate subdomains in
    # production (e.g. Railway's *.up.railway.app) — browsers treat that as
    # cross-site, so a "lax" cookie is never sent on the admin panel's
    # cross-origin fetch(), silently breaking every request after login.
    # "none" (paired with "secure", already true in production) is required
    # for the cookie to actually come back.
    base_settings = get_settings()
    prod_settings = base_settings.model_copy(update={"app_env": "production"})
    app.dependency_overrides[get_settings] = lambda: prod_settings
    client = TestClient(app)
    try:
        response = client.post("/api/v1/admin/login", json={"password": prod_settings.admin_password})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    set_cookie_header = response.headers["set-cookie"]
    assert "samesite=none" in set_cookie_header.lower()
    assert "secure" in set_cookie_header.lower()


def test_admin_jobs_reports_latest_run_per_job_name(db_session):
    now = datetime.now(timezone.utc)
    db_session.add(JobRun(job_name="news_ingestion", started_at=now - timedelta(hours=2), finished_at=now - timedelta(hours=1), status="success"))
    db_session.add(JobRun(job_name="news_ingestion", started_at=now, finished_at=None, status="running"))
    db_session.commit()

    client = _client(db_session)
    try:
        _login(client)
        response = client.get("/api/v1/admin/jobs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "running"


def test_admin_alerts_filters_unacknowledged(db_session):
    db_session.add(DataQualityAlert(severity="warning", category="provider_error", message="fmp 402'd"))
    ack = DataQualityAlert(severity="info", category="missing_data", message="no fundamentals for XYZ")
    ack.acknowledged_at = datetime.now(timezone.utc)
    db_session.add(ack)
    db_session.commit()

    client = _client(db_session)
    try:
        _login(client)
        response = client.get("/api/v1/admin/alerts?unacknowledged_only=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["message"] == "fmp 402'd"


def test_admin_acknowledge_alert(db_session):
    alert = DataQualityAlert(severity="error", category="provider_error", message="alpaca down")
    db_session.add(alert)
    db_session.commit()

    client = _client(db_session)
    try:
        _login(client)
        response = client.post(f"/api/v1/admin/alerts/{alert.id}/acknowledge")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db_session.refresh(alert)
    assert alert.acknowledged_at is not None


def test_admin_challenger_approve_promotes_and_retires_champion(db_session):
    champion = _make_model_version(db_session, "old-champion", "champion")
    challenger = _make_model_version(db_session, "new-challenger", "challenger")
    db_session.commit()

    client = _client(db_session)
    try:
        _login(client)
        pending = client.get("/api/v1/admin/challengers/pending")
        assert pending.status_code == 200
        assert len(pending.json()["challengers"]) == 1

        response = client.post(f"/api/v1/admin/challengers/{challenger.id}/approve")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db_session.refresh(champion)
    db_session.refresh(challenger)
    assert champion.status == "retired"
    assert challenger.status == "champion"
    assert challenger.promoted_at is not None


def test_admin_challenger_approve_retires_all_champions_if_more_than_one_exists(db_session):
    # Regression test: a real incident left the database with two rows
    # marked status='champion' at once (see train_baseline_models' matching
    # fix) — a single scalar()-fetch-then-mutate here would only retire one
    # of them, leaving a stale champion behind after approval.
    champion_1 = _make_model_version(db_session, "old-champion-1", "champion")
    champion_2 = _make_model_version(db_session, "old-champion-2", "champion")
    challenger = _make_model_version(db_session, "new-challenger", "challenger")
    db_session.commit()

    client = _client(db_session)
    try:
        _login(client)
        response = client.post(f"/api/v1/admin/challengers/{challenger.id}/approve")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db_session.refresh(champion_1)
    db_session.refresh(champion_2)
    db_session.refresh(challenger)
    assert champion_1.status == "retired"
    assert champion_2.status == "retired"
    assert challenger.status == "champion"


def test_admin_challenger_reject_retires_without_touching_champion(db_session):
    champion = _make_model_version(db_session, "champ", "champion")
    challenger = _make_model_version(db_session, "weak-challenger", "challenger")
    db_session.commit()

    client = _client(db_session)
    try:
        _login(client)
        response = client.post(f"/api/v1/admin/challengers/{challenger.id}/reject")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    db_session.refresh(champion)
    db_session.refresh(challenger)
    assert champion.status == "champion"
    assert challenger.status == "retired"


def test_admin_challenger_approve_returns_404_for_non_challenger(db_session):
    champion = _make_model_version(db_session, "champ", "champion")
    db_session.commit()

    client = _client(db_session)
    try:
        _login(client)
        response = client.post(f"/api/v1/admin/challengers/{champion.id}/approve")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_admin_credit_topup_and_status_roundtrip(db_session):
    client = _client(db_session)
    try:
        _login(client)
        topup = client.post(
            "/api/v1/admin/credit-topups",
            json={"amount_usd": 25.0, "topped_up_at": datetime.now(timezone.utc).isoformat(), "note": "initial load"},
        )
        assert topup.status_code == 200

        status_response = client.get("/api/v1/admin/credit-status")
    finally:
        app.dependency_overrides.clear()

    assert status_response.status_code == 200
    body = status_response.json()
    assert body["total_topped_up_usd"] == 25.0
    assert body["estimated_remaining_usd"] == 25.0


def test_admin_news_rollout_progress_reports_not_eligible_with_no_data(db_session):
    client = _client(db_session)
    try:
        _login(client)
        response = client.get("/api/v1/admin/news-rollout-progress")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is False
