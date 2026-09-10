from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.data_quality_alert import DataQualityAlert
from app.models.feature_snapshot import FeatureSnapshot
from app.models.model_version import ModelVersion
from app.models.prediction import Prediction, PredictionResult, PredictionRun
from app.models.security import Security
from app.services.champion_monitor_service import DEGRADATION_THRESHOLD, check_champion_performance
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]


def _security_id(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    return db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id


def _champion(db_session, baseline_accuracy=0.60):
    mv = ModelVersion(
        version_label="champ", algorithm="random_forest", feature_set="price_fundamentals_macro",
        trained_at=datetime.now(timezone.utc), status="champion", promoted_at=datetime.now(timezone.utc),
        hyperparameters={}, metrics={"validation": {"directional_accuracy": baseline_accuracy}},
    )
    db_session.add(mv)
    db_session.flush()
    return mv


def _add_evaluated_prediction(db_session, security_id, model_version_id, day, direction_correct):
    run = PredictionRun(
        generated_at=datetime.now(timezone.utc), model_version_id=model_version_id,
        run_type="final", target_session_date=day, status="completed",
    )
    db_session.add(run)
    db_session.flush()
    snapshot = FeatureSnapshot(security_id=security_id, as_of=datetime.now(timezone.utc), features={})
    db_session.add(snapshot)
    db_session.flush()
    prediction = Prediction(
        prediction_run_id=run.id, security_id=security_id, rank=1, ai_score=90.0,
        raw_predicted_excess_return=0.01, confidence="High", explanation="test",
        feature_snapshot_id=snapshot.id, price_at_prediction=100.0,
    )
    db_session.add(prediction)
    db_session.flush()
    db_session.add(
        PredictionResult(
            prediction_id=prediction.id, actual_return=0.01, benchmark_return=0.0,
            actual_excess_return=0.01, prediction_error=0.0,
            direction_correct=direction_correct, evaluated_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()


def test_check_champion_performance_no_champion(db_session):
    result = check_champion_performance(db_session)
    assert result == {"checked": False, "reason": "no champion model_version exists"}


def test_check_champion_performance_no_evaluated_predictions_yet(db_session):
    _champion(db_session)
    result = check_champion_performance(db_session)
    assert result["checked"] is True
    assert result["degraded"] is False


def test_check_champion_performance_not_degraded_within_threshold(db_session):
    security_id = _security_id(db_session)
    champion = _champion(db_session, baseline_accuracy=0.55)
    today = date.today()
    # 5 correct, 5 incorrect over the trailing window -> 50% accuracy, only
    # 5 points below the 55% baseline — under the 10-point threshold.
    for i in range(10):
        _add_evaluated_prediction(db_session, security_id, champion.id, today - timedelta(days=i), i % 2 == 0)
    db_session.commit()

    result = check_champion_performance(db_session)

    assert result["degraded"] is False
    assert db_session.scalar(select(DataQualityAlert)) is None


def test_check_champion_performance_flags_real_degradation(db_session):
    security_id = _security_id(db_session)
    champion = _champion(db_session, baseline_accuracy=0.60)
    today = date.today()
    # All wrong over the trailing window -> 0% accuracy, 60 points below
    # baseline — well past DEGRADATION_THRESHOLD.
    for i in range(10):
        _add_evaluated_prediction(db_session, security_id, champion.id, today - timedelta(days=i), False)
    db_session.commit()

    result = check_champion_performance(db_session)

    assert result["degraded"] is True
    assert result["baseline_accuracy"] == 0.60
    assert result["trailing_accuracy"] == 0.0

    alert = db_session.scalar(select(DataQualityAlert))
    assert alert is not None
    assert alert.category == "champion_performance_degraded"
    assert alert.severity == "warning"
    assert alert.detail["drop"] > DEGRADATION_THRESHOLD
