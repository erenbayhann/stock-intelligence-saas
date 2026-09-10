from datetime import datetime, timezone

import httpx
from dateutil import parser as dateutil_parser

from app.providers.news.base import NewsProvider, RawArticle

_BASE_URL = "https://api.marketaux.com/v1/news/all"


class MarketauxNewsProvider(NewsProvider):
    """Marketaux (spec §4, secondary NewsProvider) — broad market-wide
    sentiment context only, per data-ingestion-plan_1.md §1/§2: its 100
    requests/day free-tier budget is too tight for per-ticker polling, so this
    implementation only supports the broad (tickers=None) query mode.
    """

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("Marketaux API key must not be empty")
        self._api_key = api_key
        self._timeout = timeout

    def fetch_articles(
        self, since: datetime, tickers: dict[str, str] | None = None
    ) -> list[RawArticle]:
        if tickers:
            raise ValueError(
                "MarketauxNewsProvider only supports broad market-wide queries "
                "(tickers=None) per data-ingestion-plan_1.md §1 — its free-tier "
                "budget is too tight for per-ticker polling"
            )

        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(
                _BASE_URL,
                params={
                    "api_token": self._api_key,
                    "language": "en",
                    "limit": 3,
                    "published_after": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
                },
            )
            response.raise_for_status()
            payload = response.json()

        return [self._to_raw_article(raw) for raw in payload.get("data", [])]

    def _to_raw_article(self, raw: dict) -> RawArticle:
        return RawArticle(
            source="marketaux",
            source_article_id=raw.get("uuid"),
            title=raw.get("title", ""),
            url=raw["url"],
            published_time=dateutil_parser.isoparse(raw["published_at"]).astimezone(timezone.utc),
            raw_payload=raw,
            matched_tickers=(),  # broad query — not ticker-scoped (see class docstring)
        )
