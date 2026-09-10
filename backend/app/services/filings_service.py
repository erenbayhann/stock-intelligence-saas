from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.filing import Filing
from app.providers.filings.sec_edgar import RawFiling, SECEdgarFilingsProvider


def fetch_and_store_filings(
    db: Session, security_id: int, cik: str, provider: SECEdgarFilingsProvider
) -> dict:
    filings: list[RawFiling] = provider.get_recent_filings(cik)
    if not filings:
        return {"filings_written": 0}

    rows = [
        {
            "security_id": security_id,
            "filing_type": f.filing_type,
            "accession_number": f.accession_number,
            "filed_at": f.filed_at,
            "period_of_report": f.period_of_report,
            "url": f.url,
            "source": "sec_edgar",
            "raw_payload": f.raw_payload,
        }
        for f in filings
    ]

    stmt = insert(Filing).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["security_id", "accession_number"])
    db.execute(stmt)
    db.commit()
    return {"filings_written": len(rows)}
