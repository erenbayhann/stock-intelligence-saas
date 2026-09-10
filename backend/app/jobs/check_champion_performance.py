"""CLI entrypoint: python -m app.jobs.check_champion_performance

spec §14/§20: absolute performance degradation monitoring — a *relative*
champion/challenger comparison (spec §12) can never catch the champion's
own performance drifting down over time in a changing market. This checks
the current champion's trailing 30-day directional accuracy against its own
validation-time baseline and raises a data_quality_alerts warning if it has
dropped meaningfully — it never auto-replaces or auto-pauses the champion.
"""

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.champion_monitor_service import check_champion_performance
from app.services.job_run_service import track_job_run

logger = logging.getLogger(__name__)

JOB_NAME = "champion_performance_check"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            result = check_champion_performance(db, job_run_id=job_run.id)
            job_run.job_metadata = result
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
