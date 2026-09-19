"""CLI entrypoint: python -m app.jobs.generate_news_picks [--date YYYY-MM-DD]

Locks the news-only top picks for a session (see news_pick_service) on the
ranking model's exact cycle, ~09:15 ET before the open. With --date, reconstructs
the picks for an earlier session whose lock moment already passed: only news
that was both published and classified by that session's 09:15 ET cutoff is
used, and the row records that it was written later.
"""

import argparse
import logging
from datetime import date, datetime, timezone

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.job_run_service import track_job_run
from app.services.news_pick_service import (
    ET,
    NewsPicksAlreadyExistError,
    generate_news_pick_run,
    lock_moment,
)
from app.services.universe_service import load_constituents

logger = logging.getLogger(__name__)

JOB_NAME = "news_pick_generation"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="reconstruct picks for this past session date (ET)")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    target_session_date = args.date
    as_of = None
    if target_session_date is not None:
        now = datetime.now(timezone.utc)
        if target_session_date > now.astimezone(ET).date():
            raise SystemExit(f"--date {target_session_date} is in the future")
        as_of = min(lock_moment(target_session_date), now)

    universe_tickers = {row["ticker"] for row in load_constituents()}

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            try:
                result = generate_news_pick_run(db, universe_tickers, target_session_date, as_of)
            except NewsPicksAlreadyExistError as exc:
                logger.info(str(exc))
                result = {"skipped": True, "reason": str(exc)}
            job_run.job_metadata = result
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
