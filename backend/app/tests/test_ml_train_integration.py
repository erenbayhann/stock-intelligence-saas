import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.ml.dataset import FEATURE_COLUMNS
from app.ml.train import ARTIFACT_DIR, train_baseline_models
from app.models.feature_snapshot import FeatureSnapshot
from app.models.market_price import MarketPrice
from app.models.model_version import ModelVersion
from app.models.security import Security
from app.models.training_run import TrainingRun
from app.services.feature_service import historical_as_of_cutoffs
from app.services.universe_service import seed_benchmarks, seed_universe

TICKERS = ["AAPL", "MSFT", "JPM", "XOM", "KO"]
SAMPLE_UNIVERSE = [
    {"ticker": t, "name": t, "sector": "Test Sector", "exchange": "NASDAQ", "cik": f"000000{i}"}
    for i, t in enumerate(TICKERS)
]


def _trading_days(n: int) -> list[date]:
    days = []
    d = date(2024, 1, 1)
    while len(days) < n:
        if d.weekday() < 5:  # skip weekends -> a plausible trading calendar
            days.append(d)
        d += timedelta(days=1)
    return days


def test_train_baseline_models_end_to_end(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.ml.train.ARTIFACT_DIR", tmp_path)

    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)

    rng = random.Random(42)
    security_ids = {
        t: db_session.scalar(select(Security).where(Security.ticker == t)).id for t in TICKERS
    }
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id

    days = _trading_days(60)
    prices = {t: 100.0 for t in TICKERS}
    spy_price = 500.0

    for day in days:
        spy_price *= 1 + rng.uniform(-0.01, 0.01)
        db_session.add(
            MarketPrice(
                security_id=spy_id, ts=datetime(day.year, day.month, day.day, 4, tzinfo=timezone.utc),
                session_type="regular", open=spy_price, high=spy_price, low=spy_price, close=spy_price,
                volume=1_000_000, source="alpaca_iex",
            )
        )
        _, intraday_cutoff = historical_as_of_cutoffs(day)
        for t in TICKERS:
            prices[t] *= 1 + rng.uniform(-0.02, 0.02)
            db_session.add(
                MarketPrice(
                    security_id=security_ids[t], ts=datetime(day.year, day.month, day.day, 4, tzinfo=timezone.utc),
                    session_type="regular", open=prices[t], high=prices[t], low=prices[t], close=prices[t],
                    volume=1_000_000, source="alpaca_iex",
                )
            )
            features = {col: rng.uniform(-1, 1) for col in FEATURE_COLUMNS}
            db_session.add(
                FeatureSnapshot(security_id=security_ids[t], as_of=intraday_cutoff, features=features)
            )

    db_session.commit()

    results = train_baseline_models(db_session, days[0], days[-1], set(TICKERS))

    assert set(results.keys()) == {"ridge", "random_forest"}
    statuses = {algo: r["status"] for algo, r in results.items()}
    assert sorted(statuses.values()) == ["champion", "retired"]

    model_versions = db_session.scalars(select(ModelVersion)).all()
    assert len(model_versions) == 2
    assert {mv.status for mv in model_versions} == {"champion", "retired"}
    assert all(mv.feature_set == "price_fundamentals_macro" for mv in model_versions)

    training_runs = db_session.scalars(select(TrainingRun)).all()
    assert len(training_runs) == 2
    assert all(tr.resulting_model_version_id is not None for tr in training_runs)

    champion_label = next(r["version_label"] for r in results.values() if r["status"] == "champion")
    assert (tmp_path / f"{champion_label}.joblib").exists()
