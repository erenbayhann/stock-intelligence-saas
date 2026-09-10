"""CLI entrypoint: python -m app.jobs.train_model

Phase 5 (spec §26 item 5): trains the two spec §9 baseline models (Ridge
regression, Random Forest) on Phase 4's point-in-time-correct historical
dataset, evaluates ranking quality (spec §14) on a chronological
train/validation/test split (spec §21 — never shuffled), and promotes
whichever ranks better on validation to champion (spec §12 — the first
models ever trained have no incumbent to beat).
"""

import logging
from datetime import date, timedelta

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.ml.train import train_baseline_models
from app.services.job_run_service import track_job_run
from app.services.universe_service import load_constituents

logger = logging.getLogger(__name__)

JOB_NAME = "weekly_training"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    end_date = date.today()
    start_date = end_date - timedelta(days=settings.historical_dataset_days)
    universe_tickers = {row["ticker"] for row in load_constituents()}

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            results = train_baseline_models(db, start_date, end_date, universe_tickers)
            job_run.job_metadata = results
            result = job_run.job_metadata
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
