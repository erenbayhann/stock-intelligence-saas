import logging
from datetime import datetime, timezone

import httpx
from dateutil import parser as dateutil_parser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.providers.news.base import NewsProvider, RawArticle

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_BATCH_SIZE = 8  # tickers per OR'd query, per data-ingestion-plan_1.md §2
_MAX_RECORDS = 250  # GDELT's documented max for mode=artlist


class GDELTRateLimitError(Exception):
    pass


class GDELTNewsProvider(NewsProvider):
    """GDELT DOC 2.0 API (spec §4, primary NewsProvider). Free, no API key,
    but shares an undocumented per-IP rate limit — data-ingestion-plan_1.md §5
    flags this explicitly and asks for conservative pacing plus 429 backoff.

    Per-ticker coverage is done via batched OR'd phrase queries (§2 of that
    plan) rather than one query per ticker, since GDELT has no per-symbol
    lookup endpoint.
    """

    def __init__(self, timeout: float = 30.0, batch_size: int = _BATCH_SIZE) -> None:
        self._timeout = timeout
        self._batch_size = batch_size
        # Tickers whose batch failed on the most recent fetch_articles() call
        # (after exhausting retries) — callers can log this for visibility
        # even though a partial fetch does not raise (see fetch_articles).
        self.last_failed_tickers: list[str] = []

    def fetch_articles(
        self, since: datetime, tickers: dict[str, str] | None = None
    ) -> list[RawArticle]:
        if not tickers:
            raise ValueError(
                "GDELTNewsProvider.fetch_articles requires a non-empty tickers mapping "
                "(ticker -> search phrase); use fetch_thematic() for macro/thematic queries"
            )

        articles: list[RawArticle] = []
        items = list(tickers.items())
        self.last_failed_tickers = []
        with httpx.Client(timeout=self._timeout) as client:
            for i in range(0, len(items), self._batch_size):
                batch = dict(items[i : i + self._batch_size])
                try:
                    articles.extend(self._fetch_batch(client, batch, since))
                except Exception:
                    # One batch exhausting retries must never discard the
                    # articles already fetched from earlier batches in this
                    # same call — isolate failures per batch, not per call.
                    self.last_failed_tickers.extend(batch.keys())
                    logger.warning(
                        "GDELT batch failed for tickers %s, skipping", list(batch.keys()), exc_info=True
                    )

        if self.last_failed_tickers and not articles:
            raise GDELTRateLimitError(f"all batches failed: {self.last_failed_tickers}")
        return articles

    def fetch_thematic(self, since: datetime, keywords: list[str]) -> list[RawArticle]:
        """Broad macro/thematic sweep (e.g. Fed policy, tariffs) — not scoped
        to any ticker, so matched_tickers is always empty on the result.
        """
        query = "(" + " OR ".join(f'"{kw}"' for kw in keywords) + ") sourcelang:english"
        with httpx.Client(timeout=self._timeout) as client:
            payload = self._get(client, query, since)
        return [self._to_raw_article(raw, matched_tickers=()) for raw in payload.get("articles", [])]

    def _fetch_batch(
        self, client: httpx.Client, batch: dict[str, str], since: datetime
    ) -> list[RawArticle]:
        phrases = sorted(set(batch.values()))
        query = "(" + " OR ".join(f'"{p}"' for p in phrases) + ") sourcelang:english"
        payload = self._get(client, query, since)

        articles = []
        for raw in payload.get("articles", []):
            title_lower = (raw.get("title") or "").lower()
            matched = tuple(
                ticker for ticker, phrase in batch.items() if phrase.lower() in title_lower
            )
            articles.append(self._to_raw_article(raw, matched_tickers=matched))
        return articles

    def _to_raw_article(self, raw: dict, matched_tickers: tuple[str, ...]) -> RawArticle:
        return RawArticle(
            source="gdelt",
            source_article_id=None,  # GDELT has no stable per-article id; dedup by URL (news_service)
            title=raw.get("title", ""),
            url=raw["url"],
            published_time=_parse_seendate(raw.get("seendate")),
            raw_payload=raw,
            matched_tickers=matched_tickers,
        )

    @retry(
        retry=retry_if_exception_type(GDELTRateLimitError),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _get(self, client: httpx.Client, query: str, since: datetime) -> dict:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "sort": "datedesc",
            "maxrecords": _MAX_RECORDS,
            "startdatetime": since.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "enddatetime": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        }
        response = client.get(_BASE_URL, params=params)
        if response.status_code == 429:
            logger.warning("GDELT rate limit hit, backing off")
            raise GDELTRateLimitError()
        response.raise_for_status()

        # GDELT returns a plain-text rate-limit notice (HTTP 200) rather than
        # JSON when it's throttling — treat that the same as a real 429.
        text = response.text.lstrip()
        if not text.startswith("{"):
            logger.warning("GDELT returned a non-JSON response, treating as rate limit: %s", text[:200])
            raise GDELTRateLimitError()

        return response.json()


def _parse_seendate(seendate: str | None) -> datetime:
    if not seendate:
        return datetime.now(timezone.utc)
    try:
        # GDELT's documented format: YYYYMMDDTHHMMSSZ
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return dateutil_parser.isoparse(seendate).astimezone(timezone.utc)
