from datetime import datetime, timezone

from sqlalchemy import select

from app.models.news import NewsArticle, NewsCompanyLink
from app.models.security import Security
from app.providers.llm.news_extractor import LLMProviderError, NewsExtraction
from app.providers.news.base import RawArticle
from app.services.news_service import (
    build_ticker_search_phrases,
    enrich_unprocessed_articles,
    store_articles,
)
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
    {"ticker": "GOOGL", "name": "Alphabet Inc. (Class A)", "sector": "Communication Services", "exchange": "NASDAQ", "cik": "0001652044"},
]


def _article(url: str, source: str = "gdelt", source_article_id: str | None = None, matched=()):
    return RawArticle(
        source=source,
        source_article_id=source_article_id,
        title=f"Headline about {url}",
        url=url,
        published_time=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        raw_payload={},
        matched_tickers=matched,
    )


def test_build_ticker_search_phrases_strips_parenthetical_suffix(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)

    phrases = build_ticker_search_phrases(db_session)

    assert phrases["AAPL"] == "Apple Inc."
    assert phrases["GOOGL"] == "Alphabet Inc."  # "(Class A)" stripped


def test_store_articles_dedupes_by_url_across_sources(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}

    articles = [
        _article("https://example.com/a", source="gdelt", matched=("AAPL",)),
        _article("https://example.com/a", source="marketaux", source_article_id="uuid-1"),  # same URL, different source
    ]

    result = store_articles(db_session, articles, ticker_to_security_id)

    assert result["inserted"] == 1
    assert result["skipped_duplicate"] == 1
    rows = db_session.scalars(select(NewsArticle)).all()
    assert len(rows) == 1


def test_store_articles_creates_company_links_for_matched_tickers(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}

    store_articles(db_session, [_article("https://example.com/b", matched=("AAPL",))], ticker_to_security_id)

    links = db_session.scalars(select(NewsCompanyLink)).all()
    assert len(links) == 1
    assert float(links[0].relevance) == 1.0


def test_store_articles_is_idempotent_on_marketaux_uuid(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {}

    article = _article("https://example.com/c", source="marketaux", source_article_id="uuid-42")
    store_articles(db_session, [article], ticker_to_security_id)
    result = store_articles(db_session, [article], ticker_to_security_id)

    assert result["inserted"] == 0
    assert result["skipped_duplicate"] == 1
    assert db_session.scalar(select(NewsArticle).where(NewsArticle.url == "https://example.com/c")) is not None


class FakeExtractor:
    def __init__(self, result: NewsExtraction | Exception):
        self._result = result

    def extract(self, **kwargs):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_enrich_unprocessed_articles_success(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}
    store_articles(db_session, [_article("https://example.com/d", matched=("AAPL",))], ticker_to_security_id)

    extractor = FakeExtractor(
        NewsExtraction(sentiment=0.6, event_category="Earnings", importance=0.8, tokens_in=50, tokens_out=20)
    )
    result = enrich_unprocessed_articles(db_session, extractor, limit=10)

    assert result == {"enriched": 1, "failed": 0, "llm_tokens_in": 50, "llm_tokens_out": 20}
    article = db_session.scalar(select(NewsArticle).where(NewsArticle.url == "https://example.com/d"))
    assert article.event_category == "Earnings"
    assert float(article.sentiment) == 0.6


def test_enrich_unprocessed_articles_logs_alert_on_llm_failure(db_session):
    from app.models.data_quality_alert import DataQualityAlert

    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}
    store_articles(db_session, [_article("https://example.com/e", matched=("AAPL",))], ticker_to_security_id)

    extractor = FakeExtractor(LLMProviderError("rate_limited", "429"))
    result = enrich_unprocessed_articles(db_session, extractor, limit=10)

    assert result["enriched"] == 0
    assert result["failed"] == 1
    article = db_session.scalar(select(NewsArticle).where(NewsArticle.url == "https://example.com/e"))
    assert article.sentiment is None  # NULL, not fabricated, per spec §5

    alerts = db_session.scalars(select(DataQualityAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].category == "llm_provider_error"
    assert alerts[0].detail["kind"] == "rate_limited"
