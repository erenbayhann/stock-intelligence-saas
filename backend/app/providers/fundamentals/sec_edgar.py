import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Real-world XBRL tagging isn't standardized across companies/years — try
# tags in order, use the first one present. Only concepts with a small,
# well-standardized tag set are attempted; anything requiring guesswork
# (EBITDA has no single tag) is deliberately left out (see
# app/services/fundamentals_service.py for what's derived from these).
_FLOW_TAG_ALIASES: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "operating_income": ["OperatingIncomeLoss"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "dividends_per_share": ["CommonStockDividendsPerShareDeclared"],
}
_INSTANT_TAG_ALIASES: dict[str, list[str]] = {
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
}
_SHARES_OUTSTANDING_TAG = "EntityCommonStockSharesOutstanding"  # dei taxonomy, not us-gaap

_QUARTERLY_DURATION_DAYS = (75, 105)  # loose bounds around ~91 days
_ANNUAL_DURATION_DAYS = (350, 380)  # loose bounds around ~365 days
_SHARES_LOOKUP_WINDOW_DAYS = 60  # cover-page share count vs. fiscal period_end
_CHAIN_TOLERANCE_DAYS = 1  # some filers' quarter boundaries are off by a day


@dataclass(frozen=True)
class RawPeriodFacts:
    """Raw XBRL facts for one reporting period_end, before any derived ratio
    is computed (spec §7's derived ratios are computed downstream in
    fundamentals_service.py, some of which also need market price).
    """

    period_end: date
    filed_at: datetime
    source_form: str
    revenue: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    operating_income: float | None = None
    assets: float | None = None
    liabilities: float | None = None
    equity: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    dividends_per_share: float | None = None
    shares_outstanding: float | None = None
    raw_payload: dict = field(default_factory=dict)


class SECEdgarFundamentalsProvider:
    """SEC EDGAR XBRL companyfacts (spec §4) — the primary FundamentalsProvider
    for this project. Chosen over FMP as primary despite the original plan
    (data-ingestion-plan_1.md listed FMP first) because real testing in
    Phase 1 showed FMP's free tier gates ~60% of the S&P 100 behind a paid
    plan (402 responses), while EDGAR is free and covers 100% of tickers —
    evidence-based deviation from the original plan, per spec §27
    ("data quality > following a plan that evidence has since contradicted").

    Note on Q4: companies never tag a standalone ~91-day fact for their
    fiscal Q4 — only Q1-Q3 are individually reported; Q4 must be derived as
    (annual - Q1 - Q2 - Q3). This provider does that derivation for every
    flow concept (revenue, net_income, eps_diluted, etc.), verified against
    real Apple data (derived FY2025 Q4 diluted EPS ≈ $1.84, matching Apple's
    actual reported figure).
    """

    def __init__(self, user_agent: str, timeout: float = 30.0) -> None:
        if not user_agent:
            raise ValueError("SEC_EDGAR_USER_AGENT must not be empty (SEC fair-access policy)")
        self._headers = {"User-Agent": user_agent}
        self._timeout = timeout

    def get_quarterly_facts(self, cik: str, limit_periods: int = 12) -> list[RawPeriodFacts]:
        cik_padded = cik.zfill(10)
        with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
            response = client.get(_BASE_URL.format(cik=cik_padded))
            response.raise_for_status()
            payload = response.json()

        facts = payload.get("facts", {})
        us_gaap = facts.get("us-gaap", {})
        dei = facts.get("dei", {})

        by_period: dict[date, dict] = {}

        for field_name, tag_options in _FLOW_TAG_ALIASES.items():
            # Merge entries across ALL alias tags, not just the first one that
            # exists — companies switch XBRL tags for the same line item over
            # time (e.g. XOM tags recent revenue under "Revenues" but older
            # revenue under "RevenueFromContractWithCustomerExcludingAssessedTax";
            # picking only the first-found tag silently loses recent data).
            all_unit_entries = self._all_entries(us_gaap, tag_options)
            quarterly = self._dedupe_by_end(e for e in all_unit_entries if self._duration_in(e, _QUARTERLY_DURATION_DAYS))
            annual = self._dedupe_by_end(e for e in all_unit_entries if self._duration_in(e, _ANNUAL_DURATION_DAYS))
            derived_q4 = self._derive_q4(quarterly, annual)
            for e in list(quarterly.values()) + derived_q4:
                self._merge_into_by_period(by_period, field_name, e)

        for field_name, tag_options in _INSTANT_TAG_ALIASES.items():
            for e in self._all_entries(us_gaap, tag_options):
                if "start" in e:  # instant facts have no "start"
                    continue
                self._merge_into_by_period(by_period, field_name, e)

        self._join_shares_outstanding(by_period, dei)

        results = [
            RawPeriodFacts(
                period_end=period_end,
                filed_at=datetime.fromisoformat(row["filed"]).replace(tzinfo=timezone.utc),
                source_form=row["form"],
                revenue=row.get("revenue"),
                net_income=row.get("net_income"),
                eps_diluted=row.get("eps_diluted"),
                operating_income=row.get("operating_income"),
                assets=row.get("assets"),
                liabilities=row.get("liabilities"),
                equity=row.get("equity"),
                operating_cash_flow=row.get("operating_cash_flow"),
                capex=row.get("capex"),
                dividends_per_share=row.get("dividends_per_share"),
                shares_outstanding=row.get("shares_outstanding"),
                raw_payload=row["raw"],
            )
            for period_end, row in by_period.items()
        ]
        results.sort(key=lambda r: r.period_end, reverse=True)
        return results[:limit_periods]

    @staticmethod
    def _merge_into_by_period(by_period: dict, field_name: str, e: dict) -> None:
        period_end = date.fromisoformat(e["end"])
        row = by_period.setdefault(period_end, {"filed": e["filed"], "form": e["form"], "raw": {}})
        row[field_name] = e["val"]
        row["raw"][field_name] = e
        if e["filed"] >= row["filed"]:
            row["filed"] = e["filed"]
            row["form"] = e["form"]

    @staticmethod
    def _dedupe_by_end(entries) -> dict[str, dict]:
        """Same (start,end) can appear multiple times across filings (e.g. as
        a comparative prior-year figure) — keep the most-recently-filed one.
        """
        by_end: dict[str, dict] = {}
        for e in entries:
            end = e["end"]
            if end not in by_end or e["filed"] >= by_end[end]["filed"]:
                by_end[end] = e
        return by_end

    @staticmethod
    def _derive_q4(quarterly: dict[str, dict], annual: dict[str, dict]) -> list[dict]:
        """Q4 = annual - Q1 - Q2 - Q3, found by tiling each annual period's
        [start, end) into three quarterly chunks plus an implied fourth.
        """
        by_start = {e["start"]: e for e in quarterly.values()}

        def find_by_start(target: str) -> dict | None:
            t = date.fromisoformat(target)
            for delta in range(-_CHAIN_TOLERANCE_DAYS, _CHAIN_TOLERANCE_DAYS + 1):
                candidate = by_start.get((t + timedelta(days=delta)).isoformat())
                if candidate:
                    return candidate
            return None

        derived = []
        for annual_entry in annual.values():
            q1 = find_by_start(annual_entry["start"])
            q2 = find_by_start(q1["end"]) if q1 else None
            q3 = find_by_start(q2["end"]) if q2 else None
            if not (q1 and q2 and q3):
                continue
            gap_days = (date.fromisoformat(annual_entry["end"]) - date.fromisoformat(q3["end"])).days
            if not (_QUARTERLY_DURATION_DAYS[0] <= gap_days <= _QUARTERLY_DURATION_DAYS[1]):
                continue
            q4_value = annual_entry["val"] - q1["val"] - q2["val"] - q3["val"]
            derived.append(
                {
                    "start": q3["end"],
                    "end": annual_entry["end"],
                    "val": q4_value,
                    "filed": annual_entry["filed"],
                    "form": annual_entry["form"] + " (derived Q4)",
                }
            )
        return derived

    @staticmethod
    def _join_shares_outstanding(by_period: dict, dei: dict) -> None:
        # dei:EntityCommonStockSharesOutstanding is a 10-Q/10-K *cover-page*
        # count, dated a few days before/after filing — its `end` never
        # exactly matches a fiscal period_end, so join by nearest date within
        # a bounded window rather than an exact match, which found nothing.
        shares_entry = dei.get(_SHARES_OUTSTANDING_TAG)
        if not shares_entry:
            return
        shares_points = sorted(
            (date.fromisoformat(e["end"]), e["val"])
            for unit_entries in shares_entry["units"].values()
            for e in unit_entries
        )
        if not shares_points:
            return
        for period_end, row in by_period.items():
            closest = min(shares_points, key=lambda p: abs((p[0] - period_end).days))
            if abs((closest[0] - period_end).days) <= _SHARES_LOOKUP_WINDOW_DAYS:
                row["shares_outstanding"] = closest[1]

    @staticmethod
    def _all_entries(us_gaap: dict, tag_options: list[str]) -> list[dict]:
        """All fact entries across every alias tag for a concept, pooled
        together — see the call site for why this must not stop at the
        first tag that merely exists.
        """
        entries: list[dict] = []
        for tag in tag_options:
            concept = us_gaap.get(tag)
            if not concept:
                continue
            for unit_entries in concept["units"].values():
                entries.extend(unit_entries)
        return entries

    @staticmethod
    def _duration_in(entry: dict, bounds: tuple[int, int]) -> bool:
        if "start" not in entry:
            return False
        days = (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
        return bounds[0] <= days <= bounds[1]
