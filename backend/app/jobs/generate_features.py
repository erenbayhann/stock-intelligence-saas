"""CLI entrypoint: python -m app.jobs.generate_features

Computes one feature_snapshots row per S&P 100 security (never the
benchmark itself) as of now, per spec §6/§7/§8/§5, with point-in-time
correctness enforced at every lookup (see app/services/feature_service.py).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.company import Company
from app.models.security import Security
from app.services.feature_service import (
    compute_benchmark_features,
    compute_macro_features,
    compute_sector_peer_returns_20d,
    generate_feature_snapshot,
)
from app.services.job_run_service import track_job_run
from app.services.universe_service import load_constituents

logger = logging.getLogger(__name__)

JOB_NAME = "feature_generation"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    as_of = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            universe_tickers = {row["ticker"] for row in load_constituents()}

            securities = db.execute(
                select(Security.id, Security.ticker, Company.sector)
                .join(Company, Security.company_id == Company.id)
                .where(Security.is_active.is_(True), Security.ticker.in_(universe_tickers))
            ).all()

            benchmark_features, benchmark_return_20d = compute_benchmark_features(db, as_of)
            sector_peer_returns_20d = compute_sector_peer_returns_20d(db, as_of, universe_tickers)
            macro_features = compute_macro_features(db, as_of)

            written = 0
            for security_id, ticker, sector in securities:
                generate_feature_snapshot(
                    db,
                    security_id,
                    sector,
                    market_as_of=as_of,
                    intraday_as_of=as_of,
                    benchmark_features=benchmark_features,
                    benchmark_return_20d=benchmark_return_20d,
                    sector_peer_returns_20d=sector_peer_returns_20d,
                    macro_features=macro_features,
                    snapshot_as_of=as_of,
                )
                written += 1
            db.commit()

            job_run.job_metadata = {"snapshots_written": written, "as_of": as_of.isoformat()}
            result = job_run.job_metadata
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
