import logging
from datetime import date, datetime, timezone

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.providers.market_data.base import Bar, MarketDataProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
_CHUNK_SIZE = 30  # keep query strings and response payloads modest per request


class AlpacaRateLimitError(Exception):
    pass


class AlpacaMarketDataProvider(MarketDataProvider):
    """Real Alpaca IEX-feed implementation of MarketDataProvider (spec §4, primary
    per data-ingestion-plan.md §1). Tags every bar source='alpaca_iex' so a later
    swap to a consolidated-tape provider is visible in the data, not just the code.
    """

    def __init__(self, api_key: str, api_secret: str, timeout: float = 30.0) -> None:
        if not api_key or not api_secret:
            raise ValueError("Alpaca API key/secret must not be empty")
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }
        self._timeout = timeout

    def get_daily_bars(self, tickers: list[str], start: date, end: date) -> list[Bar]:
        bars: list[Bar] = []
        with httpx.Client(timeout=self._timeout, headers=self._headers) as client:
            for i in range(0, len(tickers), _CHUNK_SIZE):
                chunk = tickers[i : i + _CHUNK_SIZE]
                bars.extend(self._fetch_chunk(client, chunk, start, end))
        return bars

    def _fetch_chunk(
        self, client: httpx.Client, tickers: list[str], start: date, end: date
    ) -> list[Bar]:
        bars: list[Bar] = []
        page_token: str | None = None
        while True:
            params = {
                "symbols": ",".join(tickers),
                "timeframe": "1Day",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "feed": "iex",
                "limit": 10000,
                "adjustment": "raw",
            }
            if page_token:
                params["page_token"] = page_token

            payload = self._get(client, params)
            for symbol, raw_bars in (payload.get("bars") or {}).items():
                for raw in raw_bars:
                    bars.append(
                        Bar(
                            ticker=symbol,
                            ts=datetime.fromisoformat(raw["t"].replace("Z", "+00:00")).astimezone(
                                timezone.utc
                            ),
                            session_type="regular",
                            open=float(raw["o"]),
                            high=float(raw["h"]),
                            low=float(raw["l"]),
                            close=float(raw["c"]),
                            volume=int(raw["v"]),
                            source="alpaca_iex",
                        )
                    )

            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return bars

    @retry(
        retry=retry_if_exception_type(AlpacaRateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, client: httpx.Client, params: dict) -> dict:
        response = client.get(_BASE_URL, params=params)
        if response.status_code == 429:
            logger.warning("Alpaca rate limit hit, backing off")
            raise AlpacaRateLimitError()
        response.raise_for_status()
        return response.json()
