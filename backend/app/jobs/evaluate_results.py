"""CLI entrypoint: python -m app.jobs.evaluate_results

Phase 7 (spec §26 item 7): computes realized outcomes for every prediction
whose target session has closed (spec §13) — a prediction with no closing
data yet is correctly left unevaluated, not skipped due to a bug.
"""

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.job_run_service import track_job_run
from app.services.result_evaluation_service import evaluate_pending_predictions

logger = logging.getLogger(__name__)

JOB_NAME = "result_evaluation"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            result = evaluate_pending_predictions(db)
            job_run.job_metadata = result
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
