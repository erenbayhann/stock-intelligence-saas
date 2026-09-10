from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models.fundamentals import Fundamentals
from app.models.market_price import MarketPrice
from app.providers.fundamentals.sec_edgar import RawPeriodFacts
from app.services.fundamentals_service import compute_and_store_fundamentals
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]


class FakeFundamentalsProvider:
    def __init__(self, periods: list[RawPeriodFacts]):
        self._periods = periods

    def get_quarterly_facts(self, cik: str, limit_periods: int = 12) -> list[RawPeriodFacts]:
        return self._periods


def _period(period_end, filed_at, **kwargs) -> RawPeriodFacts:
    return RawPeriodFacts(period_end=period_end, filed_at=filed_at, source_form="10-Q", **kwargs)


def test_revenue_growth_computed_from_same_quarter_prior_year(db_session):
    sec_id = _seed(db_session)
    periods = [
        _period(date(2025, 3, 31), datetime(2025, 5, 1, tzinfo=timezone.utc), revenue=100.0),
        _period(date(2026, 3, 31), datetime(2026, 5, 1, tzinfo=timezone.utc), revenue=120.0),
    ]
    provider = FakeFundamentalsProvider(periods)

    compute_and_store_fundamentals(db_session, sec_id, "0000320193", provider)

    row = db_session.scalar(
        select(Fundamentals).where(Fundamentals.security_id == sec_id, Fundamentals.period_end == date(2026, 3, 31))
    )
    assert float(row.revenue_growth) == 0.2  # (120-100)/100


def test_market_cap_uses_price_on_or_before_filed_at(db_session):
    sec_id = _seed(db_session)
    db_session.add(
        MarketPrice(
            security_id=sec_id,
            ts=datetime(2026, 4, 30, tzinfo=timezone.utc),
            session_type="regular",
            open=10, high=10, low=10, close=10.0,
            volume=1000,
            source="alpaca_iex",
        )
    )
    db_session.commit()

    periods = [
        _period(
            date(2026, 3, 31),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            shares_outstanding=1_000_000.0,
        )
    ]
    provider = FakeFundamentalsProvider(periods)

    compute_and_store_fundamentals(db_session, sec_id, "0000320193", provider)

    row = db_session.scalar(select(Fundamentals).where(Fundamentals.security_id == sec_id))
    assert float(row.market_cap) == 10.0 * 1_000_000.0


def test_ttm_eps_requires_all_four_quarters(db_session):
    sec_id = _seed(db_session)
    # Only 3 of the trailing 4 quarters have eps_diluted — pe_ratio must stay
    # NULL rather than silently sum a partial TTM (spec §27: never fabricate).
    periods = [
        _period(date(2025, 6, 30), datetime(2025, 8, 1, tzinfo=timezone.utc), eps_diluted=1.0),
        _period(date(2025, 9, 30), datetime(2025, 11, 1, tzinfo=timezone.utc), eps_diluted=1.0),
        _period(date(2025, 12, 31), datetime(2026, 2, 1, tzinfo=timezone.utc), eps_diluted=None),
        _period(date(2026, 3, 31), datetime(2026, 5, 1, tzinfo=timezone.utc), eps_diluted=1.0),
    ]
    provider = FakeFundamentalsProvider(periods)

    compute_and_store_fundamentals(db_session, sec_id, "0000320193", provider)

    row = db_session.scalar(
        select(Fundamentals).where(Fundamentals.security_id == sec_id, Fundamentals.period_end == date(2026, 3, 31))
    )
    assert row.pe_ratio is None


def test_upsert_is_idempotent(db_session):
    sec_id = _seed(db_session)
    provider = FakeFundamentalsProvider(
        [_period(date(2026, 3, 31), datetime(2026, 5, 1, tzinfo=timezone.utc), revenue=100.0)]
    )

    compute_and_store_fundamentals(db_session, sec_id, "0000320193", provider)
    compute_and_store_fundamentals(db_session, sec_id, "0000320193", provider)

    rows = db_session.scalars(select(Fundamentals).where(Fundamentals.security_id == sec_id)).all()
    assert len(rows) == 1


def _seed(db_session) -> int:
    from app.models.security import Security

    seed_universe(db_session, SAMPLE_UNIVERSE)
    return db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
