from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.model_version import ModelVersion
from app.models.training_run import TrainingRun


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _make_model_version(db_session, label="test-model", status="champion"):
    mv = ModelVersion(
        version_label=label, algorithm="random_forest", feature_set="price_fundamentals_macro",
        trained_at=datetime.now(timezone.utc), status=status, hyperparameters={"n_estimators": 300},
        metrics={"test": {"mean_rank_ic": 0.0123}},
    )
    db_session.add(mv)
    db_session.flush()
    return mv


def test_model_versions_lists_headline_test_metrics(db_session):
    _make_model_version(db_session)
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/model/versions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    versions = response.json()["versions"]
    assert len(versions) == 1
    assert versions[0]["status"] == "champion"
    assert versions[0]["headline_metrics"]["mean_rank_ic"] == 0.0123


def test_model_version_detail_includes_training_run_windows(db_session):
    mv = _make_model_version(db_session)
    training_run = TrainingRun(
        started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        train_window_start=date(2024, 1, 1), train_window_end=date(2025, 12, 31),
        validation_window_start=date(2026, 1, 1), validation_window_end=date(2026, 3, 31),
        test_window_start=date(2026, 4, 1), test_window_end=date(2026, 6, 30),
        status="completed", notes="baseline champion training run",
        resulting_model_version_id=mv.id,
    )
    db_session.add(training_run)
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get(f"/api/v1/model/versions/{mv.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["algorithm"] == "random_forest"
    assert body["training_run"]["test_window"] == ["2026-04-01", "2026-06-30"]


def test_model_version_detail_returns_404_for_unknown_id(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/model/versions/999999")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
