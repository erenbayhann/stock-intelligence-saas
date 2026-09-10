"""CLI entrypoint: python -m app.jobs.ingest_macro

Pulls the fixed macro series (spec §8) from FRED, including real point-in-time
revision vintages — see app/providers/macro/fred.py for how.
"""

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.providers.macro.fred import DEFAULT_SERIES, FREDMacroProvider
from app.services.job_run_service import track_job_run
from app.services.macro_service import fetch_and_store_macro

logger = logging.getLogger(__name__)

JOB_NAME = "macro_ingestion"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    provider = FREDMacroProvider(api_key=settings.fred_api_key)

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            result = fetch_and_store_macro(db, provider, DEFAULT_SERIES)
            job_run.job_metadata = result
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
