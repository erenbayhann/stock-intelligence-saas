"""CLI entrypoint: python -m app.jobs.spotcheck_fmp

Manual cross-check tool (data-ingestion-plan.md §1): compares Alpaca's stored
EOD close for a handful of tickers against FMP's independent EOD close and
logs any material discrepancy. Not part of the scheduled ingestion pipeline.
"""

import logging

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.market_price import MarketPrice
from app.models.security import Security
from app.providers.market_data.fmp import FMPSpotCheckProvider

logger = logging.getLogger(__name__)

DISCREPANCY_THRESHOLD_PCT = 0.5  # flag if Alpaca vs FMP close differs by more than this %


def main(sample_size: int = 5) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    provider = FMPSpotCheckProvider(api_key=settings.fmp_api_key)

    db = SessionLocal()
    try:
        securities = db.scalars(
            select(Security).where(Security.is_active.is_(True)).limit(sample_size)
        ).all()

        for security in securities:
            latest_bar = db.scalar(
                select(MarketPrice)
                .where(
                    MarketPrice.security_id == security.id,
                    MarketPrice.session_type == "regular",
                    MarketPrice.source == "alpaca_iex",
                )
                .order_by(MarketPrice.ts.desc())
            )
            if latest_bar is None:
                logger.info("%s: no Alpaca bars stored yet, skipping", security.ticker)
                continue

            bar_date = latest_bar.ts.date()
            try:
                fmp_close = provider.get_eod_close(security.ticker, bar_date)
            except httpx.HTTPStatusError as exc:
                # FMP's free tier gates some symbols behind a paid plan (402) —
                # a real provider limitation (data-ingestion-plan.md §1), not a bug.
                # Skip that ticker rather than fail the whole spot-check run.
                logger.info("%s: FMP unavailable (%s), skipping", security.ticker, exc.response.status_code)
                continue
            if fmp_close is None:
                logger.info("%s: FMP has no data for %s", security.ticker, bar_date)
                continue

            alpaca_close = float(latest_bar.close)
            diff_pct = abs(alpaca_close - fmp_close) / fmp_close * 100
            level = logger.warning if diff_pct > DISCREPANCY_THRESHOLD_PCT else logger.info
            level(
                "%s %s: alpaca=%.4f fmp=%.4f diff=%.3f%%",
                security.ticker,
                bar_date,
                alpaca_close,
                fmp_close,
                diff_pct,
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
