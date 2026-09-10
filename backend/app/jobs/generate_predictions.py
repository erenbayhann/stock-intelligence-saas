"""CLI entrypoint: python -m app.jobs.generate_predictions

Phase 6 (spec §26 item 6): scores the S&P 100 universe with the current
champion model and locks the top 5 into an immutable prediction snapshot
(spec §11 — never UPDATEd once written; a later run is a new snapshot).
"""

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.job_run_service import track_job_run
from app.services.prediction_service import (
    PredictionAlreadyExistsError,
    generate_final_prediction_run,
)
from app.services.universe_service import load_constituents

logger = logging.getLogger(__name__)

JOB_NAME = "prediction_generation"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    universe_tickers = {row["ticker"] for row in load_constituents()}

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            try:
                result = generate_final_prediction_run(db, universe_tickers)
            except PredictionAlreadyExistsError as exc:
                logger.info(str(exc))
                result = {"skipped": True, "reason": str(exc)}
            job_run.job_metadata = result
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
