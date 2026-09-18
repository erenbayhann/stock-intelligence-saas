from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models.market_price import MarketPrice
from app.models.security import Security
from app.services.label_service import next_trading_session_after
from app.services.universe_service import seed_benchmarks


def _spy_bar(security_id, ts):
    return MarketPrice(
        security_id=security_id, ts=ts, session_type="regular",
        open=100.0, high=100.0, low=100.0, close=100.0, volume=1, source="alpaca_iex",
    )


def test_next_trading_session_after_same_day_when_published_before_real_close(db_session):
    # Regression for a real production bug: daily bars are stamped with a
    # nominal start-of-day ts (04:00 UTC), not the real ~16:00 ET close.
    # Comparing against that nominal ts directly (ts > published_time)
    # wrongly required the NEXT day's bar for news published later in the
    # UTC day but still hours before the real close.
    seed_benchmarks(db_session)
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id
    db_session.add(_spy_bar(spy_id, datetime(2026, 9, 18, 4, 0, tzinfo=timezone.utc)))
    db_session.commit()

    # 14:00 UTC = 10:00 ET on 2026-09-18 — well before that day's ~16:00 ET close.
    published = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)

    assert next_trading_session_after(db_session, published) == date(2026, 9, 18)


def test_next_trading_session_after_next_day_when_published_after_real_close(db_session):
    seed_benchmarks(db_session)
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id
    db_session.add(_spy_bar(spy_id, datetime(2026, 9, 18, 4, 0, tzinfo=timezone.utc)))
    db_session.add(_spy_bar(spy_id, datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)))
    db_session.commit()

    # 23:00 UTC = 19:00 ET on 2026-09-18 — after that day's real close.
    published = datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc)

    assert next_trading_session_after(db_session, published) == date(2026, 9, 19)


def test_next_trading_session_after_returns_none_when_reacting_session_not_ingested_yet(db_session):
    seed_benchmarks(db_session)
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id
    db_session.add(_spy_bar(spy_id, datetime(2026, 9, 18, 4, 0, tzinfo=timezone.utc)))
    db_session.commit()

    # Published after the 18th's close, but the 19th's bar hasn't landed yet.
    published = datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc)

    assert next_trading_session_after(db_session, published) is None


def test_next_trading_session_after_returns_none_with_no_benchmark(db_session):
    published = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)
    assert next_trading_session_after(db_session, published) is None
