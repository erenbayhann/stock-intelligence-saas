from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.models.feature_snapshot import FeatureSnapshot
from app.models.market_price import MarketPrice
from app.models.model_version import ModelVersion
from app.models.prediction import Prediction, PredictionResult, PredictionRun
from app.models.security import Security
from app.services.result_evaluation_service import evaluate_pending_predictions
from app.services.universe_service import seed_benchmarks, seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]


def _bar(security_id, d: date, close: float):
    return MarketPrice(
        security_id=security_id,
        ts=datetime(d.year, d.month, d.day, 4, tzinfo=timezone.utc),
        session_type="regular",
        open=close, high=close, low=close, close=close,
        volume=1_000_000, source="alpaca_iex",
    )


def _setup(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id
    return aapl_id, spy_id


def _make_prediction(db_session, security_id, target_day, raw_predicted_excess_return, model_version_id=None):
    if model_version_id is None:
        mv = ModelVersion(
            version_label=f"test-{target_day.isoformat()}", algorithm="ridge",
            feature_set="price_fundamentals_macro", trained_at=datetime.now(timezone.utc),
            status="champion", hyperparameters={}, metrics={},
        )
        db_session.add(mv)
        db_session.flush()
        model_version_id = mv.id

    run = PredictionRun(
        generated_at=datetime.now(timezone.utc), model_version_id=model_version_id,
        run_type="final", target_session_date=target_day, status="completed",
    )
    db_session.add(run)
    db_session.flush()

    snapshot = FeatureSnapshot(
        security_id=security_id, as_of=datetime.now(timezone.utc), features={},
    )
    db_session.add(snapshot)
    db_session.flush()

    prediction = Prediction(
        prediction_run_id=run.id, security_id=security_id, rank=1, ai_score=90.0,
        raw_predicted_excess_return=raw_predicted_excess_return, confidence="High",
        explanation="test", feature_snapshot_id=snapshot.id, price_at_prediction=100.0,
    )
    db_session.add(prediction)
    db_session.flush()
    return prediction


def test_evaluate_pending_predictions_evaluates_a_closed_session(db_session):
    aapl_id, spy_id = _setup(db_session)
    prior_day, target_day = date(2026, 6, 10), date(2026, 6, 11)

    db_session.add_all([_bar(aapl_id, prior_day, 100.0), _bar(aapl_id, target_day, 105.0)])
    db_session.add_all([_bar(spy_id, prior_day, 500.0), _bar(spy_id, target_day, 502.5)])
    prediction = _make_prediction(db_session, aapl_id, target_day, raw_predicted_excess_return=0.01)
    db_session.commit()

    result = evaluate_pending_predictions(db_session)

    assert result == {"evaluated": 1, "not_yet_closed": 0}
    pr = db_session.scalar(select(PredictionResult).where(PredictionResult.prediction_id == prediction.id))
    assert pr is not None
    assert float(pr.actual_return) == (105.0 - 100.0) / 100.0  # 0.05
    assert float(pr.benchmark_return) == (502.5 - 500.0) / 500.0  # 0.005
    assert float(pr.actual_excess_return) == pytest.approx(0.045)
    assert float(pr.prediction_error) == pytest.approx(0.01 - 0.045)
    assert pr.direction_correct is True  # both predicted (+0.01) and actual (+0.045) are positive
    assert pr.evaluated_at is not None


def test_evaluate_pending_predictions_skips_a_session_that_has_not_closed_yet(db_session):
    aapl_id, spy_id = _setup(db_session)
    target_day = date(2026, 6, 11)
    # Only a prior-day bar exists — target_day's own session hasn't closed.
    db_session.add(_bar(aapl_id, date(2026, 6, 10), 100.0))
    db_session.add(_bar(spy_id, date(2026, 6, 10), 500.0))
    _make_prediction(db_session, aapl_id, target_day, raw_predicted_excess_return=0.01)
    db_session.commit()

    result = evaluate_pending_predictions(db_session)

    assert result == {"evaluated": 0, "not_yet_closed": 1}
    assert db_session.scalar(select(PredictionResult)) is None


def test_evaluate_pending_predictions_is_idempotent(db_session):
    aapl_id, spy_id = _setup(db_session)
    prior_day, target_day = date(2026, 6, 10), date(2026, 6, 11)
    db_session.add_all([_bar(aapl_id, prior_day, 100.0), _bar(aapl_id, target_day, 105.0)])
    db_session.add_all([_bar(spy_id, prior_day, 500.0), _bar(spy_id, target_day, 502.5)])
    _make_prediction(db_session, aapl_id, target_day, raw_predicted_excess_return=0.01)
    db_session.commit()

    evaluate_pending_predictions(db_session)
    second_result = evaluate_pending_predictions(db_session)

    assert second_result == {"evaluated": 0, "not_yet_closed": 0}
    assert len(db_session.scalars(select(PredictionResult)).all()) == 1


def test_evaluate_pending_predictions_flags_incorrect_direction(db_session):
    aapl_id, spy_id = _setup(db_session)
    prior_day, target_day = date(2026, 6, 10), date(2026, 6, 11)
    # Stock underperforms the benchmark (negative excess return)...
    db_session.add_all([_bar(aapl_id, prior_day, 100.0), _bar(aapl_id, target_day, 99.0)])
    db_session.add_all([_bar(spy_id, prior_day, 500.0), _bar(spy_id, target_day, 505.0)])
    # ...but the model predicted a POSITIVE excess return.
    prediction = _make_prediction(db_session, aapl_id, target_day, raw_predicted_excess_return=0.02)
    db_session.commit()

    evaluate_pending_predictions(db_session)

    pr = db_session.scalar(select(PredictionResult).where(PredictionResult.prediction_id == prediction.id))
    assert pr.direction_correct is False
