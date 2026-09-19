import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from app.providers.news.base import NewsProvider, RawArticle

logger = logging.getLogger(__name__)

_BASE_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
# Verified live: an honest descriptive User-Agent is accepted; a request with
# no User-Agent at all gets a 404.
_USER_AGENT = "StockHyperion/0.1 (personal research project)"
_MIN_REQUEST_INTERVAL_SECONDS = 0.3
_MAX_CONSECUTIVE_FAILURES = 5


class YahooFinanceRSSError(Exception):
    pass


class YahooFinanceRSSProvider(NewsProvider):
    """Yahoo Finance's per-ticker headline RSS feed (spec §4, NewsProvider) —
    free, no API key, and genuinely ticker-scoped, unlike Marketaux's single
    market-wide query. Added because Marketaux's free tier (30 articles per
    run) was the only source actually contributing: GDELT is throttled off
    Railway's shared egress IP and Alpha Vantage's key had never been set.

    Only the headline, link, guid and publication time are kept — never the
    feed's description text. Yahoo names its per-symbol feed with `-` for
    share classes (BRK-B), so `BRK.B` is translated; the dotted form returns
    an empty feed.

    Terms note: this is a public feed meant for reading headlines; Yahoo's
    terms restrict redistribution/commercial use, the same kind of gray area
    as the other free news tiers (see the legality discussion in
    docs/ai-stock-ranking-mvp-spec.md §23). Switch it off with
    YAHOO_RSS_ENABLED=false — nothing else depends on it.
    """

    def __init__(self, timeout: float = 15.0, items_per_ticker: int = 4) -> None:
        self._timeout = timeout
        self._items_per_ticker = items_per_ticker
        # Tickers whose feed could not be fetched/parsed on the most recent
        # fetch_articles() call — callers surface this as a data-quality alert.
        self.last_failed_tickers: list[str] = []

    def fetch_articles(
        self, since: datetime, tickers: dict[str, str] | None = None
    ) -> list[RawArticle]:
        if not tickers:
            raise ValueError("YahooFinanceRSSProvider.fetch_articles requires a non-empty tickers mapping")

        since = since.astimezone(timezone.utc)
        self.last_failed_tickers = []
        # The same story routinely appears in several tickers' feeds — merged
        # by URL so it becomes one article linked to every ticker it appeared
        # under (news_service dedupes by URL anyway; this keeps the links).
        by_url: dict[str, dict] = {}
        consecutive_failures = 0
        symbols = list(tickers)

        with httpx.Client(timeout=self._timeout, headers={"User-Agent": _USER_AGENT}) as client:
            for index, ticker in enumerate(symbols):
                try:
                    items = self._fetch_feed(client, ticker)
                    consecutive_failures = 0
                except Exception:
                    self.last_failed_tickers.append(ticker)
                    logger.warning("Yahoo RSS failed for %s, skipping", ticker, exc_info=True)
                    consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        skipped = symbols[index + 1 :]
                        self.last_failed_tickers.extend(skipped)
                        logger.warning(
                            "Yahoo RSS: %d feeds failed in a row — abandoning this run, %d ticker(s) not attempted",
                            consecutive_failures, len(skipped),
                        )
                        break
                    continue

                recent = sorted(
                    (item for item in items if item["published_time"] >= since),
                    key=lambda item: item["published_time"],
                    reverse=True,
                )[: self._items_per_ticker]
                for item in recent:
                    entry = by_url.setdefault(item["url"], {**item, "tickers": []})
                    entry["tickers"].append(ticker)

                time.sleep(_MIN_REQUEST_INTERVAL_SECONDS)

        articles = [
            RawArticle(
                source="yahoo_finance",
                source_article_id=entry["guid"],
                title=entry["title"],
                url=entry["url"],
                published_time=entry["published_time"],
                raw_payload={"guid": entry["guid"], "pubDate": entry["pub_date"]},
                matched_tickers=tuple(entry["tickers"]),
            )
            for entry in by_url.values()
        ]

        if self.last_failed_tickers and not articles:
            raise YahooFinanceRSSError(
                f"no articles returned and {len(self.last_failed_tickers)} ticker(s) failed"
            )
        return articles

    def _fetch_feed(self, client: httpx.Client, ticker: str) -> list[dict]:
        response = client.get(
            _BASE_URL, params={"s": ticker.replace(".", "-"), "region": "US", "lang": "en-US"}
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)

        items = []
        for node in root.findall("./channel/item"):
            title = (node.findtext("title") or "").strip()
            url = (node.findtext("link") or "").strip()
            pub_date = (node.findtext("pubDate") or "").strip()
            if not title or not url or not pub_date:
                continue
            try:
                published_time = parsedate_to_datetime(pub_date).astimezone(timezone.utc)
            except (TypeError, ValueError):
                # Never substitute the fetch time — a headline's own
                # timestamp is what point-in-time correctness depends on (spec §3).
                continue
            items.append({
                "title": title, "url": url, "guid": (node.findtext("guid") or "").strip() or None,
                "pub_date": pub_date, "published_time": published_time,
            })
        return items
