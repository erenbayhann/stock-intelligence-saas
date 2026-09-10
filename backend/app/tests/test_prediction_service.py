import random
from datetime import date, datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sqlalchemy import select

from app.ml.dataset import FEATURE_COLUMNS
from app.models.model_version import ModelVersion
from app.models.prediction import Prediction, PredictionRun
from app.models.security import Security
from app.models.market_price import MarketPrice
from app.services.prediction_service import (
    NoChampionModelError,
    PredictionAlreadyExistsError,
    generate_final_prediction_run,
)
from app.services.universe_service import seed_benchmarks, seed_universe

TICKERS = [f"TCK{i}" for i in range(10)]
SAMPLE_UNIVERSE = [
    {"ticker": t, "name": t, "sector": "Test Sector", "exchange": "NASDAQ", "cik": f"00000{i}"}
    for i, t in enumerate(TICKERS)
]


def _seed_prices(db_session, days: int = 70):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)

    rng = random.Random(1)
    ids = {t: db_session.scalar(select(Security).where(Security.ticker == t)).id for t in TICKERS}
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id

    today = date.today()
    trading_days = [today - timedelta(days=i) for i in range(days, 0, -1)]
    prices = {t: 100.0 for t in TICKERS}
    spy_price = 500.0

    for d in trading_days:
        spy_price *= 1 + rng.uniform(-0.005, 0.005)
        db_session.add(_bar(spy_id, d, spy_price))
        for t in TICKERS:
            prices[t] *= 1 + rng.uniform(-0.02, 0.02)
            db_session.add(_bar(ids[t], d, prices[t]))
    db_session.commit()
    return ids


def _bar(security_id, d, close):
    return MarketPrice(
        security_id=security_id,
        ts=datetime(d.year, d.month, d.day, 4, tzinfo=timezone.utc),
        session_type="regular",
        open=close, high=close, low=close, close=close,
        volume=1_000_000, source="alpaca_iex",
    )


def _seed_champion(db_session, monkeypatch, tmp_path):
    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.normal(size=(50, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    y = rng.normal(size=50)
    pipeline = Pipeline([("impute", SimpleImputer(strategy="median")), ("model", RandomForestRegressor(n_estimators=10, random_state=0))])
    pipeline.fit(X, y)

    monkeypatch.setattr("app.services.prediction_service.ARTIFACT_DIR", tmp_path)
    version_label = "random_forest-test"
    joblib.dump(pipeline, tmp_path / f"{version_label}.joblib")

    db_session.add(
        ModelVersion(
            version_label=version_label, algorithm="random_forest", feature_set="price_fundamentals_macro",
            trained_at=datetime.now(timezone.utc), status="champion", promoted_at=datetime.now(timezone.utc),
            hyperparameters={}, metrics={},
        )
    )
    db_session.commit()


def test_generate_final_prediction_run_creates_top5(db_session, monkeypatch, tmp_path):
    _seed_prices(db_session)
    _seed_champion(db_session, monkeypatch, tmp_path)

    result = generate_final_prediction_run(db_session, set(TICKERS), target_session_date=date(2026, 1, 5))

    assert len(result["top5"]) == 5
    assert result["candidates_scored"] == 10

    predictions = db_session.scalars(select(Prediction).order_by(Prediction.rank)).all()
    assert len(predictions) == 5
    assert [p.rank for p in predictions] == [1, 2, 3, 4, 5]
    for p in predictions:
        assert 0 <= float(p.ai_score) <= 100
        assert p.confidence in {"High", "Medium", "Low"}
        assert p.explanation
        assert float(p.price_at_prediction) > 0

    run = db_session.scalar(select(PredictionRun))
    assert run.run_type == "final"
    assert run.target_session_date == date(2026, 1, 5)


def test_generate_final_prediction_run_is_not_rerun_for_the_same_day(db_session, monkeypatch, tmp_path):
    _seed_prices(db_session)
    _seed_champion(db_session, monkeypatch, tmp_path)

    generate_final_prediction_run(db_session, set(TICKERS), target_session_date=date(2026, 1, 5))

    with pytest.raises(PredictionAlreadyExistsError):
        generate_final_prediction_run(db_session, set(TICKERS), target_session_date=date(2026, 1, 5))

    # still only 5 predictions — the second call must not have written anything
    assert db_session.scalar(select(Prediction).limit(1)) is not None
    assert len(db_session.scalars(select(Prediction)).all()) == 5


def test_generate_final_prediction_run_requires_a_champion(db_session):
    _seed_prices(db_session)

    with pytest.raises(NoChampionModelError):
        generate_final_prediction_run(db_session, set(TICKERS), target_session_date=date(2026, 1, 5))
