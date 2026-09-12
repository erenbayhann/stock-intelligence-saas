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

    The free plan caps `limit` at 3 articles per response regardless of what's
    requested (confirmed live: requesting limit=50 still returns exactly 3,
    with `meta.found` showing thousands more available) — but `page` works
    and returns genuinely distinct articles per page (also confirmed live),
    so this paginates to use more of the 100-requests/day budget per call
    instead of the 3-articles-per-call the unpaginated version was stuck at.
    """

    _ARTICLES_PER_PAGE = 3  # the free plan's real, unconfigurable per-response cap

    def __init__(self, api_key: str, timeout: float = 30.0, max_pages_per_call: int = 10) -> None:
        if not api_key:
            raise ValueError("Marketaux API key must not be empty")
        self._api_key = api_key
        self._timeout = timeout
        self._max_pages_per_call = max_pages_per_call

    def fetch_articles(
        self, since: datetime, tickers: dict[str, str] | None = None
    ) -> list[RawArticle]:
        if tickers:
            raise ValueError(
                "MarketauxNewsProvider only supports broad market-wide queries "
                "(tickers=None) per data-ingestion-plan_1.md §1 — its free-tier "
                "budget is too tight for per-ticker polling"
            )

        articles: list[RawArticle] = []
        with httpx.Client(timeout=self._timeout) as client:
            for page in range(1, self._max_pages_per_call + 1):
                response = client.get(
                    _BASE_URL,
                    params={
                        "api_token": self._api_key,
                        "language": "en",
                        "limit": self._ARTICLES_PER_PAGE,
                        "page": page,
                        "published_after": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
                    },
                )
                response.raise_for_status()
                payload = response.json()
                page_articles = payload.get("data", [])
                if not page_articles:
                    break
                articles.extend(self._to_raw_article(raw) for raw in page_articles)

        return articles

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
