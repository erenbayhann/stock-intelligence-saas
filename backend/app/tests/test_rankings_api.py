from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_db
from app.main import app
from app.models.feature_snapshot import FeatureSnapshot
from app.models.model_version import ModelVersion
from app.models.news import NewsArticle
from app.models.prediction import Prediction, PredictionNewsLink, PredictionResult, PredictionRun
from app.models.security import Security
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _make_model_version(db_session, label="test-model"):
    mv = ModelVersion(
        version_label=label, algorithm="ridge", feature_set="price_fundamentals_macro",
        trained_at=datetime.now(timezone.utc), status="champion", hyperparameters={}, metrics={},
    )
    db_session.add(mv)
    db_session.flush()
    return mv


def _make_final_run_with_prediction(db_session, security_id, model_version_id, target_day, with_news=False):
    run = PredictionRun(
        generated_at=datetime.now(timezone.utc), model_version_id=model_version_id,
        run_type="final", target_session_date=target_day, status="completed",
    )
    db_session.add(run)
    db_session.flush()

    snapshot = FeatureSnapshot(security_id=security_id, as_of=datetime.now(timezone.utc), features={})
    db_session.add(snapshot)
    db_session.flush()

    prediction = Prediction(
        prediction_run_id=run.id, security_id=security_id, rank=1, ai_score=88.0,
        raw_predicted_excess_return=0.01, confidence="High", explanation="strong momentum",
        feature_snapshot_id=snapshot.id, price_at_prediction=100.0,
    )
    db_session.add(prediction)
    db_session.flush()

    if with_news:
        article = NewsArticle(
            source="marketaux", title="Apple beats earnings", url="https://example.com/a",
            published_time=datetime.now(timezone.utc),
        )
        db_session.add(article)
        db_session.flush()
        db_session.add(PredictionNewsLink(prediction_id=prediction.id, news_article_id=article.id))
        db_session.flush()

    return run, prediction


def _security_id(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    return db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id


def test_rankings_latest_returns_404_when_no_final_run(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/rankings/latest")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_rankings_latest_never_exposes_actual_return(db_session):
    security_id = _security_id(db_session)
    mv = _make_model_version(db_session)
    _make_final_run_with_prediction(db_session, security_id, mv.id, date.today(), with_news=True)
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/rankings/latest")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == mv.version_label
    assert len(body["top5"]) == 1
    item = body["top5"][0]
    assert item["ticker"] == "AAPL"
    assert item["ai_score"] == 88.0
    assert "actual_return" not in item
    assert len(item["related_news"]) == 1


def test_rankings_for_date_includes_result_once_evaluated(db_session):
    security_id = _security_id(db_session)
    mv = _make_model_version(db_session)
    target_day = date.today()
    _run, prediction = _make_final_run_with_prediction(db_session, security_id, mv.id, target_day)

    result = PredictionResult(
        prediction_id=prediction.id, actual_return=0.03, benchmark_return=0.01,
        actual_excess_return=0.02, prediction_error=0.01 - 0.02, direction_correct=True,
        evaluated_at=datetime.now(timezone.utc),
    )
    db_session.add(result)
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get(f"/api/v1/rankings/{target_day.isoformat()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["hit_rate"] == 1.0
    assert body["top5"][0]["actual_return"] == 0.03
    assert body["top5"][0]["direction_correct"] is True


def test_rankings_for_date_returns_404_for_unknown_date(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/rankings/2020-01-01")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_rankings_history_returns_items_most_recent_first(db_session):
    security_id = _security_id(db_session)
    mv = _make_model_version(db_session)
    _make_final_run_with_prediction(db_session, security_id, mv.id, date(2026, 1, 1))
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/rankings/history?limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["target_session_date"] == "2026-01-01"
    assert body["items"][0]["top_pick"]["ticker"] == "AAPL"
    assert body["items"][0]["top_pick"]["ai_score"] == 88.0
    assert body["items"][0]["top_pick"]["actual_return"] is None
    assert body["items"][0]["top_pick"]["vs_benchmark"] is None


def test_rankings_history_route_registered_before_parameterized_date_route(db_session):
    # Regression guard: /rankings/history must not be swallowed by
    # /rankings/{target_date}'s date parsing (registration order matters).
    client = _client(db_session)
    try:
        response = client.get("/api/v1/rankings/history")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
