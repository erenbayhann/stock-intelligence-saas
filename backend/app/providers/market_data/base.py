from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar for one security, tagged with the session it belongs to
    and the provider it came from — mirrors the `market_prices` table exactly
    so a provider's output can be upserted without translation.
    """

    ticker: str
    ts: datetime
    session_type: str  # 'regular' | 'pre' | 'after'
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


class MarketDataProvider(ABC):
    """Interface every market-data source implements (spec §4). New providers
    (or a mock/demo one, per §27, when no real credentials are available)
    plug in here without touching calling code.
    """

    @abstractmethod
    def get_daily_bars(
        self, tickers: list[str], start: date, end: date
    ) -> list[Bar]:
        """Regular-session daily OHLCV bars for `tickers` in [start, end], inclusive."""
        raise NotImplementedError
