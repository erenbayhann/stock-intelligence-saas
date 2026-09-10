from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models.market_price import MarketPrice
from app.models.security import Security
from app.services.feature_service import compute_market_features, historical_as_of_cutoffs
from app.services.historical_dataset_service import build_historical_dataset
from app.services.label_service import compute_realized_label, get_trading_days
from app.services.universe_service import seed_benchmarks, seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]


def _bar(security_id, day: date, close: float, hour: int = 4):
    return MarketPrice(
        security_id=security_id,
        ts=datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc),
        session_type="regular",
        open=close, high=close, low=close, close=close,
        volume=1_000_000,
        source="alpaca_iex",
    )


def _setup(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id
    return aapl_id, spy_id


def test_market_cutoff_excludes_target_days_own_bar(db_session):
    aapl_id, spy_id = _setup(db_session)
    target_day = date(2026, 6, 15)
    prior_day = date(2026, 6, 12)

    db_session.add(_bar(aapl_id, prior_day, close=100.0))
    # target_day's own bar — a real trading day already fully in the table,
    # exactly the "historical replay" scenario this cutoff exists to guard.
    db_session.add(_bar(aapl_id, target_day, close=999999.0))
    db_session.commit()

    market_cutoff, _ = historical_as_of_cutoffs(target_day)
    features = compute_market_features(db_session, aapl_id, market_cutoff)

    # Only the prior day's bar should be visible — return_1d needs 2 bars,
    # so with just one visible bar it must be None, never reflect 999999.0.
    assert features["volume"] == 1_000_000
    assert features["return_1d"] is None

    # Sanity: if we (wrongly) used a same-day-inclusive cutoff, the future
    # bar WOULD be visible — proving the two cutoffs actually behave differently.
    naive_cutoff = datetime(target_day.year, target_day.month, target_day.day, 12, tzinfo=timezone.utc)
    naive_features = compute_market_features(db_session, aapl_id, naive_cutoff)
    assert naive_features["return_1d"] == (999999.0 - 100.0) / 100.0


def test_realized_label_uses_target_days_own_close(db_session):
    aapl_id, spy_id = _setup(db_session)
    target_day = date(2026, 6, 15)
    prior_day = date(2026, 6, 12)

    db_session.add(_bar(aapl_id, prior_day, close=100.0))
    db_session.add(_bar(aapl_id, target_day, close=110.0))
    db_session.add(_bar(spy_id, prior_day, close=500.0))
    db_session.add(_bar(spy_id, target_day, close=505.0))
    db_session.commit()

    label = compute_realized_label(db_session, aapl_id, target_day)

    assert label is not None
    assert label["actual_return"] == (110.0 - 100.0) / 100.0
    assert label["benchmark_return"] == (505.0 - 500.0) / 500.0
    assert label["actual_excess_return"] == label["actual_return"] - label["benchmark_return"]


def test_realized_label_is_none_without_a_bar_on_that_day(db_session):
    aapl_id, spy_id = _setup(db_session)
    db_session.add(_bar(aapl_id, date(2026, 6, 12), close=100.0))
    db_session.commit()

    label = compute_realized_label(db_session, aapl_id, date(2026, 6, 15))

    assert label is None  # never fabricate a 0.0 return for a day with no data


def test_get_trading_days_excludes_weekends_and_gaps(db_session):
    _, spy_id = _setup(db_session)
    # Fri, then Mon (skipping the weekend) — a real trading calendar.
    db_session.add(_bar(spy_id, date(2026, 6, 12), close=500.0))
    db_session.add(_bar(spy_id, date(2026, 6, 15), close=505.0))
    db_session.commit()

    days = get_trading_days(db_session, date(2026, 6, 10), date(2026, 6, 16))

    assert days == [date(2026, 6, 12), date(2026, 6, 15)]


def test_build_historical_dataset_end_to_end(db_session):
    aapl_id, spy_id = _setup(db_session)
    days = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12), date(2026, 6, 15)]
    for i, d in enumerate(days):
        db_session.add(_bar(aapl_id, d, close=100.0 + i))
        db_session.add(_bar(spy_id, d, close=500.0 + i))
    db_session.commit()

    result = build_historical_dataset(db_session, days[0], days[-1], {"AAPL"})

    assert result["trading_days"] == 4
    assert result["snapshots_written"] == 4  # 1 security x 4 days
    # First day has no prior bar, so no label for it — 3 labeled rows.
    assert result["labeled_rows"] == 3
    assert len(result["dataset"]) == 3
    first_row = result["dataset"][0]
    assert first_row["ticker"] == "AAPL"
    assert "actual_return" in first_row
    assert "features" in first_row


def test_build_historical_dataset_is_idempotent_on_rerun(db_session):
    from sqlalchemy import select as sa_select

    from app.models.feature_snapshot import FeatureSnapshot

    aapl_id, spy_id = _setup(db_session)
    days = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    for i, d in enumerate(days):
        db_session.add(_bar(aapl_id, d, close=100.0 + i))
        db_session.add(_bar(spy_id, d, close=500.0 + i))
    db_session.commit()

    build_historical_dataset(db_session, days[0], days[-1], {"AAPL"})
    build_historical_dataset(db_session, days[0], days[-1], {"AAPL"})  # re-run over the same range

    rows = db_session.scalars(
        sa_select(FeatureSnapshot).where(FeatureSnapshot.security_id == aapl_id)
    ).all()
    assert len(rows) == 3  # not 6 — the second run replaced, not duplicated
