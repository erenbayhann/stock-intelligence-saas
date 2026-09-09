from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.market_price import MarketPrice
from app.providers.market_data.base import Bar, MarketDataProvider
from app.services.market_data_service import backfill_daily_bars
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
    {"ticker": "JPM", "name": "JPMorgan Chase", "sector": "Financials", "exchange": "NYSE", "cik": "0000019617"},
]


class FakeMarketDataProvider(MarketDataProvider):
    """Deterministic stand-in for Alpaca — no real network calls in tests."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    def get_daily_bars(self, tickers: list[str], start: date, end: date) -> list[Bar]:
        return [b for b in self._bars if b.ticker in tickers]


def _bar(ticker: str, ts: datetime, close: float) -> Bar:
    return Bar(
        ticker=ticker,
        ts=ts,
        session_type="regular",
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1_000_000,
        source="alpaca_iex",
    )


def test_backfill_writes_bars_for_active_universe(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)

    day = datetime(2026, 1, 5, tzinfo=timezone.utc)
    provider = FakeMarketDataProvider([_bar("AAPL", day, 150.0), _bar("JPM", day, 200.0)])

    result = backfill_daily_bars(
        db_session, provider, start=date(2026, 1, 1), end=date(2026, 1, 6)
    )

    assert result["bars_fetched"] == 2
    assert result["rows_written"] == 2
    assert result["tickers"] == 2

    rows = db_session.scalars(select(MarketPrice)).all()
    assert len(rows) == 2
    assert {float(r.close) for r in rows} == {150.0, 200.0}


def test_backfill_upsert_is_idempotent_and_updates_in_place(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)

    day = datetime(2026, 1, 5, tzinfo=timezone.utc)
    provider_v1 = FakeMarketDataProvider([_bar("AAPL", day, 150.0)])
    backfill_daily_bars(db_session, provider_v1, start=date(2026, 1, 1), end=date(2026, 1, 6))

    # Re-running with a corrected/updated close for the same (security, ts,
    # session_type, source) must update the existing row, not duplicate it.
    provider_v2 = FakeMarketDataProvider([_bar("AAPL", day, 151.5)])
    backfill_daily_bars(db_session, provider_v2, start=date(2026, 1, 1), end=date(2026, 1, 6))

    rows = db_session.scalars(select(MarketPrice)).all()
    assert len(rows) == 1
    assert float(rows[0].close) == 151.5


def test_backfill_with_no_active_securities_is_a_noop(db_session):
    provider = FakeMarketDataProvider([])
    result = backfill_daily_bars(db_session, provider, start=date(2026, 1, 1), end=date(2026, 1, 6))

    assert result == {"bars_fetched": 0, "rows_written": 0, "tickers": 0}


def test_backfill_handles_more_rows_than_fit_in_one_statement(db_session):
    # Postgres caps bind parameters at 65535; with 9 columns/row that's ~7281
    # rows per statement. A full 5-year/100-ticker backfill produces well over
    # that in one call, so the upsert must chunk across statement boundaries
    # without dropping or duplicating rows.
    seed_universe(db_session, SAMPLE_UNIVERSE)

    bars = [
        _bar("AAPL", datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), 100.0 + i)
        for i in range(8000)
    ]
    provider = FakeMarketDataProvider(bars)

    result = backfill_daily_bars(
        db_session, provider, start=date(2020, 1, 1), end=date(2042, 1, 1), tickers=["AAPL"]
    )

    assert result["rows_written"] == 8000
    rows = db_session.scalars(select(MarketPrice)).all()
    assert len(rows) == 8000
