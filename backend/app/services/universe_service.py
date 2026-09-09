import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.security import Security

logger = logging.getLogger(__name__)

DEFAULT_CONSTITUENTS_PATH = Path(__file__).resolve().parents[2] / "data" / "sp100_constituents.json"


def load_constituents(path: Path = DEFAULT_CONSTITUENTS_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed_universe(db: Session, constituents: list[dict] | None = None) -> dict[str, int]:
    """Idempotently upsert the S&P 100 universe (companies + securities).

    Safe to re-run: existing rows are updated in place by (cik) for companies
    and (ticker) for securities, nothing is duplicated.
    """
    constituents = constituents if constituents is not None else load_constituents()

    companies_written = 0
    securities_written = 0
    seen_tickers: set[str] = set()

    for row in constituents:
        ticker = row["ticker"]
        seen_tickers.add(ticker)

        company = db.scalar(select(Company).where(Company.cik == row["cik"]))
        if company is None:
            company = Company(cik=row["cik"], name=row["name"], sector=row["sector"])
            db.add(company)
            db.flush()
            companies_written += 1
        else:
            company.name = row["name"]
            company.sector = row["sector"]

        security = db.scalar(select(Security).where(Security.ticker == ticker))
        if security is None:
            security = Security(
                company_id=company.id,
                ticker=ticker,
                exchange=row["exchange"],
                is_active=True,
            )
            db.add(security)
            securities_written += 1
        else:
            security.company_id = company.id
            security.exchange = row["exchange"]
            security.is_active = True

    # Anything previously in the universe but no longer present in the constituent
    # list is marked inactive, never deleted (spec §13: history is never destroyed).
    active_securities = db.scalars(select(Security).where(Security.is_active.is_(True)))
    deactivated = 0
    for security in active_securities:
        if security.ticker not in seen_tickers:
            security.is_active = False
            deactivated += 1

    db.commit()
    logger.info(
        "Universe seeded: %d companies written, %d securities written, %d deactivated",
        companies_written,
        securities_written,
        deactivated,
    )
    return {
        "companies_written": companies_written,
        "securities_written": securities_written,
        "deactivated": deactivated,
        "total_constituents": len(constituents),
    }
