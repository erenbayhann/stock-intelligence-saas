import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.fundamentals import Fundamentals
from app.models.market_price import MarketPrice
from app.providers.fundamentals.sec_edgar import RawPeriodFacts, SECEdgarFundamentalsProvider

logger = logging.getLogger(__name__)

_YOY_DAYS = (350, 380)


def _pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _find_prior_year_period(periods_asc: list[RawPeriodFacts], period: RawPeriodFacts) -> RawPeriodFacts | None:
    for candidate in periods_asc:
        days = (period.period_end - candidate.period_end).days
        if _YOY_DAYS[0] <= days <= _YOY_DAYS[1]:
            return candidate
    return None


def _ttm_eps(periods_asc: list[RawPeriodFacts], period: RawPeriodFacts) -> float | None:
    """Trailing-twelve-month diluted EPS: sum of this quarter's + the 3
    preceding quarters', only if all 4 are present (never partial-sum a TTM
    figure — a 2-quarter sum silently understating TTM is worse than a NULL).
    """
    idx = periods_asc.index(period)
    if idx < 3:
        return None
    trailing = periods_asc[idx - 3 : idx + 1]
    values = [p.eps_diluted for p in trailing]
    if any(v is None for v in values):
        return None
    return sum(values)


def _price_on_or_before(db: Session, security_id: int, as_of: datetime) -> float | None:
    price = db.scalar(
        select(MarketPrice.close)
        .where(
            MarketPrice.security_id == security_id,
            MarketPrice.session_type == "regular",
            MarketPrice.ts <= as_of,
        )
        .order_by(MarketPrice.ts.desc())
        .limit(1)
    )
    return float(price) if price is not None else None


def compute_and_store_fundamentals(
    db: Session, security_id: int, cik: str, provider: SECEdgarFundamentalsProvider
) -> dict:
    """Pulls raw XBRL facts, derives spec §7's ratios where they can be
    computed reliably, and upserts one `fundamentals` row per period_end.

    ev_ebitda and net_debt_ebitda are deliberately left NULL — EBITDA has no
    single standardized XBRL tag (needs depreciation/amortization data this
    provider doesn't pull), and a heuristic guess here would be a wrong
    number silently feeding a financial model, worse than a NULL (spec §27:
    never fabricate). price_to_book/pe_ratio/market_cap/dividend_yield use
    the closing price on or before the filing's own filed_at — a snapshot
    "as of the filing," not a continuously-updated live ratio (schema §17:
    these columns live on `fundamentals`, keyed by period_end, not on a
    continuously-refreshed table).
    """
    periods_desc = provider.get_quarterly_facts(cik)
    periods_asc = sorted(periods_desc, key=lambda p: p.period_end)

    written = 0
    for period in periods_asc:
        prior_year = _find_prior_year_period(periods_asc, period)
        revenue_growth = _pct_change(period.revenue, prior_year.revenue if prior_year else None)
        earnings_growth = _pct_change(period.net_income, prior_year.net_income if prior_year else None)
        operating_margin = _safe_div(period.operating_income, period.revenue)
        debt_equity = _safe_div(period.liabilities, period.equity)
        free_cash_flow = (
            period.operating_cash_flow - period.capex
            if period.operating_cash_flow is not None and period.capex is not None
            else None
        )
        roe = _safe_div(period.net_income, period.equity)

        price = _price_on_or_before(db, security_id, period.filed_at)
        market_cap = (
            price * period.shares_outstanding if price and period.shares_outstanding else None
        )
        ttm_eps = _ttm_eps(periods_asc, period)
        pe_ratio = _safe_div(price, ttm_eps) if price else None
        book_value_per_share = _safe_div(period.equity, period.shares_outstanding)
        price_to_book = _safe_div(price, book_value_per_share) if price else None
        dividend_yield = (
            _safe_div(period.dividends_per_share * 4, price)
            if price and period.dividends_per_share
            else None
        )

        stmt = insert(Fundamentals).values(
            security_id=security_id,
            period_end=period.period_end,
            filed_at=period.filed_at,
            source="sec_edgar",
            revenue_growth=revenue_growth,
            earnings_growth=earnings_growth,
            eps=period.eps_diluted,
            pe_ratio=pe_ratio,
            price_to_book=price_to_book,
            ev_ebitda=None,
            debt_equity=debt_equity,
            net_debt_ebitda=None,
            roe=roe,
            operating_margin=operating_margin,
            free_cash_flow=free_cash_flow,
            market_cap=market_cap,
            dividend_yield=dividend_yield,
            raw_payload=period.raw_payload,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["security_id", "period_end", "source"],
            set_={
                "filed_at": stmt.excluded.filed_at,
                "revenue_growth": stmt.excluded.revenue_growth,
                "earnings_growth": stmt.excluded.earnings_growth,
                "eps": stmt.excluded.eps,
                "pe_ratio": stmt.excluded.pe_ratio,
                "price_to_book": stmt.excluded.price_to_book,
                "debt_equity": stmt.excluded.debt_equity,
                "roe": stmt.excluded.roe,
                "operating_margin": stmt.excluded.operating_margin,
                "free_cash_flow": stmt.excluded.free_cash_flow,
                "market_cap": stmt.excluded.market_cap,
                "dividend_yield": stmt.excluded.dividend_yield,
                "raw_payload": stmt.excluded.raw_payload,
            },
        )
        db.execute(stmt)
        written += 1

    db.commit()
    return {"periods_written": written}
