from sqlalchemy import select

from app.models.company import Company
from app.models.security import Security
from app.services.universe_service import seed_universe

SAMPLE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
    {"ticker": "JPM", "name": "JPMorgan Chase", "sector": "Financials", "exchange": "NYSE", "cik": "0000019617"},
]


def test_seed_universe_creates_companies_and_securities(db_session):
    result = seed_universe(db_session, SAMPLE)

    assert result["companies_written"] == 2
    assert result["securities_written"] == 2

    tickers = set(db_session.scalars(select(Security.ticker)))
    assert tickers == {"AAPL", "JPM"}

    companies = db_session.scalars(select(Company)).all()
    assert {c.cik for c in companies} == {"0000320193", "0000019617"}


def test_seed_universe_is_idempotent(db_session):
    seed_universe(db_session, SAMPLE)
    result_second_run = seed_universe(db_session, SAMPLE)

    assert result_second_run["companies_written"] == 0
    assert result_second_run["securities_written"] == 0

    tickers = list(db_session.scalars(select(Security.ticker)))
    assert len(tickers) == 2  # no duplicates


def test_seed_universe_deactivates_dropped_tickers(db_session):
    seed_universe(db_session, SAMPLE)

    smaller = [SAMPLE[0]]
    seed_universe(db_session, smaller)

    jpm = db_session.scalar(select(Security).where(Security.ticker == "JPM"))
    assert jpm is not None
    assert jpm.is_active is False

    aapl = db_session.scalar(select(Security).where(Security.ticker == "AAPL"))
    assert aapl.is_active is True
