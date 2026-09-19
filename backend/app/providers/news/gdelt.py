import logging
import time
from datetime import datetime, timezone

import httpx
from dateutil import parser as dateutil_parser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.providers.news.base import NewsProvider, RawArticle, match_tickers_by_title

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_BATCH_SIZE = 8  # tickers per OR'd query, per data-ingestion-plan_1.md §2
_MAX_RECORDS = 250  # GDELT's documented max for mode=artlist
# GDELT's own 429 body states this explicitly ("limit requests to one every
# 5 seconds") — verified live. The per-batch retry/backoff below only reacts
# AFTER a 429; for a ~100-ticker universe (13 batches of 8) fired back to
# back with no gap, most batches got 429'd on their very first attempt,
# starving out real GDELT coverage in favor of whatever other provider
# (Marketaux) has no such limit. Pacing proactively avoids triggering the
# 429 in the first place, across BOTH fetch_articles' batches and
# fetch_thematic — same provider instance, same shared limit.
_MIN_REQUEST_INTERVAL_SECONDS = 5.0
# Live production evidence (2026-09-18): pacing alone was not enough — GDELT
# kept refusing (429s across 14-50s backoffs, and outright dropped
# connections) from Railway's shared egress IP. Retrying every remaining
# batch through that just burned minutes per run and kept hammering an
# already-refusing service, so after this many batches in a row fail, the
# rest of the run is abandoned (and reported as failed, never silently lost).
_MAX_CONSECUTIVE_BATCH_FAILURES = 3
# GDELT rejects a phrase shorter than this outright ("The specified phrase is
# too short." — observed live for "Uber"), which failed every other company
# OR'd into the same batch with it.
_MIN_PHRASE_LENGTH = 5


class GDELTRateLimitError(Exception):
    pass


class GDELTQueryError(Exception):
    """GDELT understood the request and rejected the query itself (e.g. a
    too-short phrase) — retrying the identical query can never succeed, so
    unlike GDELTRateLimitError this is never retried."""


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
        # Shared pacing state across every real request this instance makes
        # (both fetch_articles' batches and fetch_thematic) — see
        # _MIN_REQUEST_INTERVAL_SECONDS.
        self._last_request_at: float | None = None

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
        consecutive_failures = 0
        with httpx.Client(timeout=self._timeout) as client:
            for i in range(0, len(items), self._batch_size):
                batch = dict(items[i : i + self._batch_size])
                try:
                    articles.extend(self._fetch_batch(client, batch, since))
                    consecutive_failures = 0
                except GDELTQueryError:
                    # Our query was bad, not GDELT down — doesn't count
                    # toward the circuit breaker below.
                    self.last_failed_tickers.extend(batch.keys())
                    logger.warning(
                        "GDELT rejected the query for tickers %s, skipping", list(batch.keys()), exc_info=True
                    )
                except Exception:
                    # One batch exhausting retries must never discard the
                    # articles already fetched from earlier batches in this
                    # same call — isolate failures per batch, not per call.
                    self.last_failed_tickers.extend(batch.keys())
                    logger.warning(
                        "GDELT batch failed for tickers %s, skipping", list(batch.keys()), exc_info=True
                    )
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_BATCH_FAILURES:
                        skipped = [ticker for ticker, _ in items[i + self._batch_size :]]
                        self.last_failed_tickers.extend(skipped)
                        logger.warning(
                            "GDELT: %d batches failed in a row — abandoning this run, %d ticker(s) not attempted",
                            consecutive_failures, len(skipped),
                        )
                        break

        if self.last_failed_tickers and not articles:
            raise GDELTRateLimitError(
                f"no articles returned and {len(self.last_failed_tickers)} ticker(s) failed: {self.last_failed_tickers}"
            )
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
        phrases = sorted({p for p in batch.values() if len(p) >= _MIN_PHRASE_LENGTH})
        if not phrases:
            return []
        query = "(" + " OR ".join(f'"{p}"' for p in phrases) + ") sourcelang:english"
        payload = self._get(client, query, since)

        articles = []
        for raw in payload.get("articles", []):
            matched = match_tickers_by_title(raw.get("title") or "", batch)
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

    def _wait_for_rate_limit(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            remaining = _MIN_REQUEST_INTERVAL_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

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
        self._wait_for_rate_limit()
        response = client.get(_BASE_URL, params=params)
        if response.status_code == 429:
            logger.warning("GDELT rate limit hit, backing off")
            raise GDELTRateLimitError()
        response.raise_for_status()

        # GDELT returns a plain-text rate-limit notice (HTTP 200) rather than
        # JSON when it's throttling — treat that the same as a real 429.
        text = response.text.lstrip()
        if not text.startswith("{"):
            if "limit requests" in text.lower():
                logger.warning("GDELT returned a rate-limit notice, backing off: %s", text[:200])
                raise GDELTRateLimitError()
            logger.warning("GDELT rejected the query: %s", text[:200])
            raise GDELTQueryError(text[:200])

        return response.json()


def _parse_seendate(seendate: str | None) -> datetime:
    if not seendate:
        return datetime.now(timezone.utc)
    try:
        # GDELT's documented format: YYYYMMDDTHHMMSSZ
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return dateutil_parser.isoparse(seendate).astimezone(timezone.utc)
