"""CLI entrypoint: python -m app.jobs.backfill_market_data

Pulls HISTORICAL_BACKFILL_YEARS of daily regular-session OHLCV bars from
Alpaca for the active universe and idempotently upserts them into
market_prices. Requires the universe to already be seeded
(see app.jobs.seed_universe).
"""

import logging
from datetime import date, timedelta

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.providers.market_data.alpaca import AlpacaMarketDataProvider
from app.services.market_data_service import backfill_daily_bars

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    provider = AlpacaMarketDataProvider(
        api_key=settings.alpaca_api_key, api_secret=settings.alpaca_api_secret
    )

    end = date.today()
    start = end - timedelta(days=365 * settings.historical_backfill_years)

    db = SessionLocal()
    try:
        result = backfill_daily_bars(db, provider, start=start, end=end)
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
