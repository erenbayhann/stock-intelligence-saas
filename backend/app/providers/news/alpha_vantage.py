import logging
from datetime import datetime, timezone

import httpx

from app.providers.news.base import NewsProvider, RawArticle

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"

# Confirmed via live testing against the real API (2026-09-12): 20 tickers in
# one comma-separated `tickers=` request succeeds, 21 fails with a generic
# "Invalid inputs" error (no per-ticker detail) — undocumented, but a real,
# hard cap. Free-tier daily budget is 25 requests/day (stated directly in the
# API's own throttle message), so covering the ~99-ticker universe (5
# requests) fits comfortably within one run, with headroom for a few runs/day
# — max_requests_per_call defaults conservatively below that.
_MAX_TICKERS_PER_REQUEST = 20

# AlphaVantage rejects tickers containing a "." (confirmed live: "BRK.B" ->
# "Invalid ticker format... can only contain alphanumeric characters, colons,
# underscores") — share-class tickers like BRK.B have no clean equivalent on
# this provider and are skipped rather than mangled into a guess.
_INVALID_TICKER_CHARS = "."


class AlphaVantageNewsProvider(NewsProvider):
    """Alpha Vantage NEWS_SENTIMENT (spec §4 secondary NewsProvider). Unlike
    Marketaux, supports real per-ticker queries with the provider's OWN
    pre-computed per-ticker relevance/sentiment — more reliable than GDELT's
    naive headline-substring ticker matching, though this implementation
    still routes sentiment through the same Claude enrichment pass as every
    other source for consistency (see app/services/news_service.py); AV's own
    scores are kept in raw_payload for future use, not applied directly yet.
    """

    def __init__(
        self, api_key: str, timeout: float = 30.0, max_requests_per_call: int = 5
    ) -> None:
        if not api_key:
            raise ValueError("Alpha Vantage API key must not be empty")
        self._api_key = api_key
        self._timeout = timeout
        self._max_requests_per_call = max_requests_per_call
        # Set when a batch comes back as a throttle notice rather than data —
        # same "200 OK with a text warning instead of real content" shape as
        # GDELT's rate limiting. Callers should surface this (data_quality_alerts),
        # not treat a resulting empty article list as "no news today."
        self.last_rate_limited = False

    def fetch_articles(
        self, since: datetime, tickers: dict[str, str] | None = None
    ) -> list[RawArticle]:
        if not tickers:
            raise ValueError(
                "AlphaVantageNewsProvider.fetch_articles requires a non-empty tickers "
                "mapping (ticker -> display name, name unused here)"
            )

        valid_tickers = [t for t in tickers if not any(c in t for c in _INVALID_TICKER_CHARS)]
        skipped = set(tickers) - set(valid_tickers)
        if skipped:
            logger.info("AlphaVantage: skipping tickers with unsupported format: %s", sorted(skipped))

        batches = [
            valid_tickers[i : i + _MAX_TICKERS_PER_REQUEST]
            for i in range(0, len(valid_tickers), _MAX_TICKERS_PER_REQUEST)
        ][: self._max_requests_per_call]

        self.last_rate_limited = False
        articles: list[RawArticle] = []
        with httpx.Client(timeout=self._timeout) as client:
            for batch in batches:
                articles.extend(self._fetch_batch(client, batch, since))
        return articles

    def _fetch_batch(self, client: httpx.Client, batch: list[str], since: datetime) -> list[RawArticle]:
        response = client.get(
            _BASE_URL,
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ",".join(batch),
                "time_from": since.astimezone(timezone.utc).strftime("%Y%m%dT%H%M"),
                "limit": 200,
                "apikey": self._api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()

        # Alpha Vantage returns HTTP 200 with a plain "Information"/"Note"
        # message body (not a 429) when the daily/per-second limit is hit —
        # same "200 that isn't really success" shape as GDELT's throttling.
        if "Information" in payload or "Note" in payload or "Error Message" in payload:
            msg = payload.get("Information") or payload.get("Note") or payload.get("Error Message")
            logger.warning("AlphaVantage NEWS_SENTIMENT non-data response: %s", msg)
            self.last_rate_limited = True
            return []

        return [self._to_raw_article(raw, set(batch)) for raw in payload.get("feed", [])]

    def _to_raw_article(self, raw: dict, requested_tickers: set[str]) -> RawArticle:
        matched = tuple(
            ts["ticker"]
            for ts in raw.get("ticker_sentiment", [])
            if ts["ticker"] in requested_tickers
        )
        return RawArticle(
            source="alpha_vantage",
            source_article_id=raw.get("url"),  # AV has no separate id field; url is already the dedup key
            title=raw.get("title", ""),
            url=raw["url"],
            published_time=_parse_time_published(raw.get("time_published")),
            raw_payload=raw,
            matched_tickers=matched,
        )


def _parse_time_published(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    # Documented format: YYYYMMDDTHHMMSS, always UTC.
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
