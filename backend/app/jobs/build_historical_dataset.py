"""CLI entrypoint: python -m app.jobs.build_historical_dataset

Phase 4 (spec §26 item 4): rebuilds point-in-time-correct historical feature
snapshots + realized labels for the trailing HISTORICAL_DATASET_DAYS days,
for every S&P 100 security. See app/services/historical_dataset_service.py
for the point-in-time mechanics and app/services/label_service.py for the
label definition (spec §2).
"""

import logging
from datetime import date, timedelta

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.historical_dataset_service import build_historical_dataset
from app.services.job_run_service import track_job_run
from app.services.universe_service import load_constituents

logger = logging.getLogger(__name__)

JOB_NAME = "historical_dataset_construction"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    end_date = date.today()
    start_date = end_date - timedelta(days=settings.historical_dataset_days)
    universe_tickers = {row["ticker"] for row in load_constituents()}

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            result = build_historical_dataset(db, start_date, end_date, universe_tickers)
            dataset_size = len(result.pop("dataset"))
            job_run.job_metadata = {**result, "dataset_rows_in_memory": dataset_size}
            result = job_run.job_metadata
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
