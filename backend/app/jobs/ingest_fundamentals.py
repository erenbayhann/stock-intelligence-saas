"""CLI entrypoint: python -m app.jobs.ingest_fundamentals

Pulls SEC EDGAR XBRL company facts for every active security with a CIK and
upserts derived fundamentals rows (spec §7). SEC EDGAR chosen as primary over
FMP — see app/providers/fundamentals/sec_edgar.py docstring for why.
"""

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.company import Company
from app.models.security import Security
from app.providers.fundamentals.sec_edgar import SECEdgarFundamentalsProvider
from app.services.data_quality_service import record_alert
from app.services.fundamentals_service import compute_and_store_fundamentals
from app.services.job_run_service import track_job_run

logger = logging.getLogger(__name__)

JOB_NAME = "fundamentals_ingestion"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    provider = SECEdgarFundamentalsProvider(user_agent=settings.sec_edgar_user_agent)

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            securities = db.execute(
                select(Security.id, Security.ticker, Security.company_id)
                .where(Security.is_active.is_(True))
            ).all()
            companies = {c.id: c.cik for c in db.scalars(select(Company))}

            periods_written = 0
            tickers_processed = 0
            tickers_skipped = 0
            for security_id, ticker, company_id in securities:
                cik = companies.get(company_id)
                if not cik:
                    tickers_skipped += 1
                    continue
                try:
                    result = compute_and_store_fundamentals(db, security_id, cik, provider)
                    periods_written += result["periods_written"]
                    tickers_processed += 1
                except Exception as exc:
                    db.rollback()
                    record_alert(
                        db,
                        severity="error",
                        category="provider_error",
                        message=f"Fundamentals ingestion failed for {ticker} (cik={cik}): {exc}",
                        job_run_id=job_run.id,
                    )
                    tickers_skipped += 1

            job_run.job_metadata = {
                "tickers_processed": tickers_processed,
                "tickers_skipped": tickers_skipped,
                "periods_written": periods_written,
            }
            result = job_run.job_metadata
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
