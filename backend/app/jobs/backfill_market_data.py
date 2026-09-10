"""CLI entrypoint: python -m app.jobs.backfill_market_data

Pulls HISTORICAL_BACKFILL_YEARS of daily regular-session OHLCV bars from
Alpaca for the active universe and idempotently upserts them into
market_prices. Requires the universe to already be seeded
(see app.jobs.seed_universe).

The scheduler (app/scheduler.py, Phase 10) calls main(days_back=5) for its
nightly EOD sync instead of the full multi-year range — data-ingestion-plan_1.md
§2 sizes the nightly pull at "well under 20 calls," which a full historical
re-fetch every night would blow through for no reason (the unique constraint
makes it idempotent, but it would still hit Alpaca for 5 years x 100 tickers
daily). 5 calendar days safely covers weekends/holidays and a single missed
scheduler run without needing to track last-successful-run state.
"""

import logging
from datetime import date, timedelta

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.providers.market_data.alpaca import AlpacaMarketDataProvider
from app.services.job_run_service import track_job_run
from app.services.market_data_service import backfill_daily_bars

logger = logging.getLogger(__name__)

JOB_NAME = "market_data_ingestion"


def main(days_back: int | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    provider = AlpacaMarketDataProvider(
        api_key=settings.alpaca_api_key, api_secret=settings.alpaca_api_secret
    )

    end = date.today()
    start = end - timedelta(days=days_back if days_back is not None else 365 * settings.historical_backfill_years)

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            result = backfill_daily_bars(db, provider, start=start, end=end)
            job_run.job_metadata = result
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
