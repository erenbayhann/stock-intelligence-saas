"""CLI entrypoint: python -m app.jobs.seed_universe

Idempotently loads backend/data/sp100_constituents.json into the
companies/securities tables.
"""

import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.universe_service import seed_universe

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    db = SessionLocal()
    try:
        result = seed_universe(db)
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
