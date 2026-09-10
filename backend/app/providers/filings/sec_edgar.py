import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# spec §17/§4: 8-K/10-Q/10-K/Form 4 — the filing types the feature/news
# pipeline cares about (earnings, material events, insider transactions).
TRACKED_FORMS = {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "4"}


@dataclass(frozen=True)
class RawFiling:
    filing_type: str
    accession_number: str
    filed_at: datetime  # EDGAR's own acceptance timestamp — the point-in-time field (§3/§4)
    period_of_report: date | None
    url: str
    raw_payload: dict


class SECEdgarFilingsProvider:
    """SEC EDGAR (spec §4, FilingsProvider) — free, no key, requires a
    descriptive User-Agent per SEC's fair-access policy.
    """

    def __init__(self, user_agent: str, timeout: float = 30.0) -> None:
        if not user_agent:
            raise ValueError("SEC_EDGAR_USER_AGENT must not be empty (SEC fair-access policy)")
        self._headers = {"User-Agent": user_agent}
        self._timeout = timeout

    def get_recent_filings(self, cik: str, limit: int = 50) -> list[RawFiling]:
        cik_padded = cik.zfill(10)
        with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
            response = client.get(_SUBMISSIONS_URL.format(cik=cik_padded))
            response.raise_for_status()
            payload = response.json()

        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filings: list[RawFiling] = []

        for i, form in enumerate(forms):
            if form not in TRACKED_FORMS:
                continue
            if len(filings) >= limit:
                break

            accession_number = recent["accessionNumber"][i]
            accession_no_dashes = accession_number.replace("-", "")
            cik_no_leading_zeros = str(int(cik_padded))
            primary_document = recent["primaryDocument"][i]
            url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik_no_leading_zeros}/{accession_no_dashes}/{primary_document}"
            )

            acceptance_raw = recent.get("acceptanceDateTime", [None] * len(forms))[i]
            filed_at = (
                dateutil_parser.isoparse(acceptance_raw).astimezone(timezone.utc)
                if acceptance_raw
                else datetime.fromisoformat(recent["filingDate"][i]).replace(tzinfo=timezone.utc)
            )

            report_date_raw = recent.get("reportDate", [None] * len(forms))[i]
            period_of_report = date.fromisoformat(report_date_raw) if report_date_raw else None

            filings.append(
                RawFiling(
                    filing_type=form,
                    accession_number=accession_number,
                    filed_at=filed_at,
                    period_of_report=period_of_report,
                    url=url,
                    raw_payload={
                        "form": form,
                        "accessionNumber": accession_number,
                        "filingDate": recent["filingDate"][i],
                        "acceptanceDateTime": acceptance_raw,
                    },
                )
            )

        return filings
