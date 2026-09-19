from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RawArticle:
    """One news article as returned by a provider, before dedup/enrichment.
    Mirrors `news_articles` closely so normalization stays a straight mapping.
    """

    source: str  # 'gdelt' | 'marketaux' | 'alpha_vantage' | 'yahoo_finance'
    title: str
    url: str
    published_time: datetime  # from the provider — NEVER the fetch/received time (spec §3)
    source_article_id: str | None = None
    raw_payload: dict = field(default_factory=dict)
    # Tickers this article was matched to (either the provider's own query
    # context, e.g. which per-ticker keyword batch returned it, or a
    # post-hoc title match against known company names for a broad query).
    matched_tickers: tuple[str, ...] = ()
    # Per-ticker relevance for tickers in matched_tickers, when a provider
    # supplies its own (e.g. Alpha Vantage's ticker_sentiment.relevance_score).
    # A ticker present in matched_tickers but absent here defaults to 1.0 in
    # store_articles — providers that only do binary title matching (GDELT,
    # Marketaux) have no finer-grained signal to offer.
    ticker_relevance: dict[str, float] = field(default_factory=dict)


def match_tickers_by_title(title: str, ticker_phrases: dict[str, str]) -> tuple[str, ...]:
    """Binary substring match: does this ticker's display-name phrase appear
    in the headline text? Shared by GDELT (its own per-ticker query batch
    already narrows candidates) and Marketaux (a single broad query, matched
    post-hoc against every known company since the query itself isn't
    ticker-scoped). Cheap and imperfect — misses a company referred to
    indirectly (e.g. "the iPhone maker" instead of "Apple Inc.").
    """
    title_lower = title.lower()
    return tuple(ticker for ticker, phrase in ticker_phrases.items() if phrase.lower() in title_lower)


class NewsProvider(ABC):
    """Interface every news source implements (spec §4). `tickers` maps ticker
    symbol -> search phrase to query for it (a bare 1-2 letter ticker like "V"
    or "T" is a poor/ambiguous search term, so the caller — which has access
    to `companies.name` — decides the actual phrase; the provider just runs
    it). `tickers=None` means a broad/market-wide query; providers that only
    support one mode should document and enforce that in their implementation.
    """

    @abstractmethod
    def fetch_articles(
        self, since: datetime, tickers: dict[str, str] | None = None
    ) -> list[RawArticle]:
        raise NotImplementedError
