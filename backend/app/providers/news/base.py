from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RawArticle:
    """One news article as returned by a provider, before dedup/enrichment.
    Mirrors `news_articles` closely so normalization stays a straight mapping.
    """

    source: str  # 'gdelt' | 'marketaux' | 'alpha_vantage'
    title: str
    url: str
    published_time: datetime  # from the provider — NEVER the fetch/received time (spec §3)
    source_article_id: str | None = None
    raw_payload: dict = field(default_factory=dict)
    # Tickers this article was matched to by the provider's own query context
    # (e.g. which per-ticker keyword batch returned it). Empty for a broad/
    # market-wide query that isn't ticker-scoped (e.g. Marketaux's role here).
    matched_tickers: tuple[str, ...] = ()


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
