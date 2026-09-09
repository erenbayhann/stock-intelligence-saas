from datetime import date

import httpx

# FMP's legacy /api/v3/historical-price-full endpoint now 403s on the free tier;
# the current "stable" endpoint returns a flat JSON array instead of {"historical": [...]}.
_BASE_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"


class FMPSpotCheckProvider:
    """FMP as a secondary/cross-check source for EOD prices (data-ingestion-plan.md §1).
    Not part of the scheduled backfill/ingestion pipeline — used only by the manual
    spot-check job to sanity-check Alpaca's numbers against an independent source.
    """

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("FMP API key must not be empty")
        self._api_key = api_key
        self._timeout = timeout

    def get_eod_close(self, ticker: str, on: date) -> float | None:
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(
                _BASE_URL,
                params={
                    "symbol": ticker,
                    "from": on.isoformat(),
                    "to": on.isoformat(),
                    "apikey": self._api_key,
                },
            )
            response.raise_for_status()
            rows = response.json()

        if not rows:
            return None
        return float(rows[0]["close"])
