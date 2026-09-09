import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.market_price import MarketPrice
from app.models.security import Security
from app.providers.market_data.base import Bar, MarketDataProvider

logger = logging.getLogger(__name__)


def backfill_daily_bars(
    db: Session,
    provider: MarketDataProvider,
    start: date,
    end: date,
    tickers: list[str] | None = None,
) -> dict[str, int]:
    """Pull daily regular-session bars for the active universe (or an explicit
    `tickers` subset) and idempotently upsert them into `market_prices`.

    Safe to re-run: the (security_id, ts, session_type, source) unique
    constraint means a repeated pull updates rows in place instead of
    duplicating them (spec §20).
    """
    securities = db.scalars(
        select(Security).where(Security.is_active.is_(True))
        if tickers is None
        else select(Security).where(Security.ticker.in_(tickers))
    ).all()
    ticker_to_security_id = {s.ticker: s.id for s in securities}

    if not ticker_to_security_id:
        logger.warning("No active securities found to backfill")
        return {"bars_fetched": 0, "rows_written": 0, "tickers": 0}

    bars = provider.get_daily_bars(list(ticker_to_security_id.keys()), start, end)
    logger.info("Fetched %d bars for %d tickers", len(bars), len(ticker_to_security_id))

    rows_written = _upsert_bars(db, bars, ticker_to_security_id)
    return {
        "bars_fetched": len(bars),
        "rows_written": rows_written,
        "tickers": len(ticker_to_security_id),
    }


def _upsert_bars(db: Session, bars: list[Bar], ticker_to_security_id: dict[str, int]) -> int:
    if not bars:
        return 0

    rows = []
    for bar in bars:
        security_id = ticker_to_security_id.get(bar.ticker)
        if security_id is None:
            continue
        rows.append(
            {
                "security_id": security_id,
                "ts": bar.ts,
                "session_type": bar.session_type,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": bar.source,
            }
        )

    if not rows:
        return 0

    # Postgres caps bind parameters at 65535 per statement; 9 columns/row means
    # a full multi-year, full-universe backfill (100k+ rows) must be chunked.
    columns_per_row = 9
    max_rows_per_statement = 65535 // columns_per_row
    written = 0
    for i in range(0, len(rows), max_rows_per_statement):
        chunk = rows[i : i + max_rows_per_statement]
        stmt = insert(MarketPrice).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["security_id", "ts", "session_type", "source"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        db.execute(stmt)
        written += len(chunk)
    db.commit()
    return written
