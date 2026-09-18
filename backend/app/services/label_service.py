import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market_price import MarketPrice
from app.models.security import Security

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "SPY"
_MARKET_CLOSE_HOUR_ET = 16


def get_trading_days(db: Session, start: date, end: date) -> list[date]:
    """Real trading days = distinct dates the benchmark actually has a
    regular-session bar for — never a generated calendar range, which would
    wrongly include weekends/holidays as if the market had been open.
    """
    benchmark = db.scalar(select(Security).where(Security.ticker == BENCHMARK_TICKER))
    if benchmark is None:
        return []
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    rows = db.scalars(
        select(MarketPrice.ts)
        .where(
            MarketPrice.security_id == benchmark.id,
            MarketPrice.session_type == "regular",
            MarketPrice.ts >= start_dt,
            MarketPrice.ts <= end_dt,
        )
        .order_by(MarketPrice.ts)
    ).all()
    return sorted({ts.date() for ts in rows})


def _close_to_close_return(db: Session, security_id: int, target_session_date: date) -> float | None:
    """target_session_date's own close vs. the immediately preceding
    trading day's close — spec §2's "next_session_stock_return" component,
    realized here after the fact (this is a LABEL, allowed to use
    target_session_date's own outcome; it must never be used as a feature
    input for that same date — see historical_as_of_cutoffs).
    """
    day_start = datetime.combine(target_session_date, time.min, tzinfo=timezone.utc)
    day_end = datetime.combine(target_session_date, time.max, tzinfo=timezone.utc)

    bars = db.execute(
        select(MarketPrice.ts, MarketPrice.close)
        .where(
            MarketPrice.security_id == security_id,
            MarketPrice.session_type == "regular",
            MarketPrice.ts <= day_end,
        )
        .order_by(MarketPrice.ts.desc())
        .limit(2)
    ).all()

    if len(bars) < 2:
        return None
    if not (day_start <= bars[0].ts <= day_end):
        return None  # no bar actually on target_session_date — not a real trading day for this security

    prior_close = float(bars[1].close)
    if prior_close == 0:
        return None
    return (float(bars[0].close) - prior_close) / prior_close


def next_trading_session_after(db: Session, after: datetime) -> date | None:
    """The first real trading day (per the benchmark's own regular-session
    bars, same "real trading days" source as get_trading_days) whose close
    happens at or after `after` and whose bar has actually been ingested —
    e.g. for overnight/after-hours news, this is the next session; for news
    published intraday before that session's real close, it's that same
    session. None if no such bar exists yet (session hasn't closed, or
    hasn't been ingested yet) — never guessed from a calendar.

    Reasons in real close-time/calendar-date space, NOT by comparing `after`
    against a bar's stored `ts` directly — a daily bar's `ts` is stamped at
    a nominal start-of-day marker, not the real ~16:00 ET close (see
    historical_as_of_cutoffs' docstring), so a raw ts comparison is wrong:
    a real production bug found this way misclassified news published
    later in the UTC day (but still hours before the real close) as
    needing to wait an entire extra session, because its timestamp already
    sat after that nominal marker.
    """
    same_day_close = datetime(
        after.year, after.month, after.day, _MARKET_CLOSE_HOUR_ET, tzinfo=ZoneInfo("America/New_York")
    ).astimezone(timezone.utc)
    candidate_date = after.date() if after < same_day_close else after.date() + timedelta(days=1)

    benchmark = db.scalar(select(Security).where(Security.ticker == BENCHMARK_TICKER))
    if benchmark is None:
        return None
    ts = db.scalar(
        select(MarketPrice.ts)
        .where(
            MarketPrice.security_id == benchmark.id,
            MarketPrice.session_type == "regular",
            MarketPrice.ts >= datetime.combine(candidate_date, time.min, tzinfo=timezone.utc),
        )
        .order_by(MarketPrice.ts.asc())
        .limit(1)
    )
    return ts.date() if ts else None


def compute_realized_label(db: Session, security_id: int, target_session_date: date) -> dict | None:
    """spec §2: next_session_stock_return - next_session_market_return.
    Returns None (never a fabricated 0.0) if either leg is unavailable —
    e.g. the security didn't trade that day, or the benchmark is missing.
    """
    benchmark = db.scalar(select(Security).where(Security.ticker == BENCHMARK_TICKER))
    if benchmark is None:
        return None

    stock_return = _close_to_close_return(db, security_id, target_session_date)
    benchmark_return = _close_to_close_return(db, benchmark.id, target_session_date)
    if stock_return is None or benchmark_return is None:
        return None

    return {
        "actual_return": stock_return,
        "benchmark_return": benchmark_return,
        "actual_excess_return": stock_return - benchmark_return,
    }
