from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.feature_snapshot import FeatureSnapshot
from app.models.model_version import ModelVersion
from app.models.prediction import Prediction, PredictionResult, PredictionRun
from app.models.security import Security
from app.services.performance_service import compute_performance_summary
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]


def _make_model_version(db_session, label="test-model"):
    mv = ModelVersion(
        version_label=label, algorithm="ridge", feature_set="price_fundamentals_macro",
        trained_at=datetime.now(timezone.utc), status="champion", hyperparameters={},
        metrics={"validation": {"directional_accuracy": 0.55}},
    )
    db_session.add(mv)
    db_session.flush()
    return mv


def _make_evaluated_prediction(
    db_session, security_id, model_version_id, target_day,
    predicted, actual_return, benchmark_return, direction_correct,
):
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
        prediction_run_id=run.id, security_id=security_id, rank=1, ai_score=90.0,
        raw_predicted_excess_return=predicted, confidence="High", explanation="test",
        feature_snapshot_id=snapshot.id, price_at_prediction=100.0,
    )
    db_session.add(prediction)
    db_session.flush()

    actual_excess_return = actual_return - benchmark_return
    result = PredictionResult(
        prediction_id=prediction.id, actual_return=actual_return, benchmark_return=benchmark_return,
        actual_excess_return=actual_excess_return, prediction_error=predicted - actual_excess_return,
        direction_correct=direction_correct, evaluated_at=datetime.now(timezone.utc),
    )
    db_session.add(result)
    db_session.flush()
    return prediction


def _security_id(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    return db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id


def test_compute_performance_summary_empty_when_no_results(db_session):
    result = compute_performance_summary(db_session, window="7d")
    assert result == {"window": "7d", "n_predictions": 0, "n_days": 0}


def test_compute_performance_summary_computes_correct_aggregates(db_session):
    security_id = _security_id(db_session)
    mv = _make_model_version(db_session)
    today = date.today()

    _make_evaluated_prediction(db_session, security_id, mv.id, today, 0.02, 0.03, 0.01, True)
    _make_evaluated_prediction(db_session, security_id, mv.id, today - timedelta(days=1), -0.01, 0.02, 0.03, False)
    db_session.commit()

    result = compute_performance_summary(db_session, window="7d")

    assert result["n_predictions"] == 2
    assert result["n_days"] == 2
    assert result["hit_rate"] == pytest.approx(0.5)
    assert result["mean_actual_return"] == pytest.approx((0.03 + 0.02) / 2)
    assert result["mean_excess_return"] == pytest.approx(((0.03 - 0.01) + (0.02 - 0.03)) / 2)


def test_compute_performance_summary_respects_window(db_session):
    security_id = _security_id(db_session)
    mv = _make_model_version(db_session)
    today = date.today()

    _make_evaluated_prediction(db_session, security_id, mv.id, today, 0.01, 0.01, 0.0, True)
    _make_evaluated_prediction(db_session, security_id, mv.id, today - timedelta(days=20), 0.01, 0.01, 0.0, True)
    db_session.commit()

    result_7d = compute_performance_summary(db_session, window="7d")
    result_30d = compute_performance_summary(db_session, window="30d")
    result_all = compute_performance_summary(db_session, window="all")

    assert result_7d["n_predictions"] == 1
    assert result_30d["n_predictions"] == 2
    assert result_all["n_predictions"] == 2


def test_compute_performance_summary_filters_by_model_version(db_session):
    # Different target_session_dates — only one 'final' prediction_run is
    # ever allowed per day (idx_one_final_run_per_day), matching how a
    # model changeover would actually look in reality: the old model's
    # predictions belong to earlier days, the new model's to later ones.
    security_id = _security_id(db_session)
    mv_old = _make_model_version(db_session, "old-model")
    mv_new = _make_model_version(db_session, "new-model")
    today = date.today()

    _make_evaluated_prediction(db_session, security_id, mv_old.id, today - timedelta(days=2), 0.01, 0.01, 0.0, True)
    _make_evaluated_prediction(db_session, security_id, mv_new.id, today - timedelta(days=1), 0.01, 0.01, 0.0, True)
    _make_evaluated_prediction(db_session, security_id, mv_new.id, today, 0.01, -0.01, 0.0, False)
    db_session.commit()

    result_new_only = compute_performance_summary(db_session, window="all", model_version_id=mv_new.id)

    assert result_new_only["n_predictions"] == 2


def test_compute_performance_summary_rejects_unknown_window(db_session):
    with pytest.raises(ValueError):
        compute_performance_summary(db_session, window="90d")
