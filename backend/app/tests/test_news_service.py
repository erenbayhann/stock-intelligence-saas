from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.market_price import MarketPrice
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.security import Security
from app.providers.llm.news_extractor import ClassificationResult, LLMProviderError, TickerClassification
from app.providers.news.base import RawArticle
from app.services.news_service import (
    TOP_NEWS_LOOKBACK_HOURS,
    build_ticker_search_phrases,
    classify_unprocessed_articles,
    get_news_history,
    get_top_news,
    store_articles,
)
from app.services.universe_service import seed_benchmarks, seed_universe

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
    def __init__(self, result: ClassificationResult | Exception):
        self._result = result

    def classify(self, **kwargs):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_classify_unprocessed_articles_success(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}
    store_articles(db_session, [_article("https://example.com/d", matched=("AAPL",))], ticker_to_security_id)

    extractor = FakeExtractor(
        ClassificationResult(
            tickers=(TickerClassification(ticker="AAPL", relevance=0.9, sentiment=0.6, event_category="Earnings", importance=0.8),),
            tokens_in=50,
            tokens_out=20,
        )
    )
    result = classify_unprocessed_articles(db_session, extractor, limit=10)

    assert result == {"classified": 1, "failed": 0, "llm_links_created": 1, "llm_tokens_in": 50, "llm_tokens_out": 20}
    article = db_session.scalar(select(NewsArticle).where(NewsArticle.url == "https://example.com/d"))
    assert article.classified_at is not None
    link = db_session.scalar(select(NewsCompanyLink).where(NewsCompanyLink.news_article_id == article.id))
    assert link.event_category == "Earnings"
    assert float(link.sentiment) == 0.6


def test_classify_unprocessed_articles_adds_sector_inferred_link_not_found_by_substring_match(db_session):
    universe = SAMPLE_UNIVERSE + [
        {"ticker": "XOM", "name": "Exxon Mobil Corp.", "sector": "Energy", "exchange": "NYSE", "cik": "0000034088"},
    ]
    seed_universe(db_session, universe)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}
    # No provider matched any ticker — a pure macro/thematic headline (like
    # GDELT's thematic sweep, which never sets matched_tickers).
    store_articles(db_session, [_article("https://example.com/oil", matched=())], ticker_to_security_id)

    extractor = FakeExtractor(
        ClassificationResult(
            tickers=(TickerClassification(ticker="XOM", relevance=0.8, sentiment=0.5, event_category="Macroeconomic exposure", importance=0.6),),
            tokens_in=100,
            tokens_out=30,
        )
    )
    result = classify_unprocessed_articles(db_session, extractor, limit=10)

    assert result["llm_links_created"] == 1
    links = db_session.scalars(select(NewsCompanyLink)).all()
    assert len(links) == 1
    assert links[0].security_id == ticker_to_security_id["XOM"]


def test_classify_unprocessed_articles_logs_alert_on_llm_failure(db_session):
    from app.models.data_quality_alert import DataQualityAlert

    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}
    store_articles(db_session, [_article("https://example.com/e", matched=("AAPL",))], ticker_to_security_id)

    extractor = FakeExtractor(LLMProviderError("rate_limited", "429"))
    result = classify_unprocessed_articles(db_session, extractor, limit=10)

    assert result["classified"] == 0
    assert result["failed"] == 1
    article = db_session.scalar(select(NewsArticle).where(NewsArticle.url == "https://example.com/e"))
    assert article.classified_at is None  # not fabricated, retried on a later run, per spec §5

    alerts = db_session.scalars(select(DataQualityAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].category == "llm_provider_error"
    assert alerts[0].detail["kind"] == "rate_limited"


def _classified_article(db_session, security_id, url, *, relevance, importance, sentiment=0.0,
                         published_time=None, event_category="Earnings"):
    published_time = published_time or datetime.now(timezone.utc)
    article = NewsArticle(
        source="gdelt", title=f"Headline {url}", url=url,
        published_time=published_time, classified_at=datetime.now(timezone.utc),
    )
    db_session.add(article)
    db_session.flush()
    db_session.add(NewsCompanyLink(
        news_article_id=article.id, security_id=security_id,
        relevance=relevance, sentiment=sentiment, event_category=event_category, importance=importance,
    ))
    db_session.commit()
    return article


def test_get_top_news_orders_by_relevance_times_importance(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    googl_id = db_session.scalar(select(Security).where(Security.ticker == "GOOGL")).id

    _classified_article(db_session, aapl_id, "https://example.com/low", relevance=0.3, importance=0.2)
    _classified_article(db_session, googl_id, "https://example.com/high", relevance=0.9, importance=0.9)

    items = get_top_news(db_session, limit=10)

    assert [i["ticker"] for i in items] == ["GOOGL", "AAPL"]
    assert items[0]["score"] == 0.81


def test_get_top_news_excludes_articles_outside_lookback_window(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    stale_time = datetime.now(timezone.utc) - timedelta(hours=TOP_NEWS_LOOKBACK_HOURS + 1)

    _classified_article(db_session, aapl_id, "https://example.com/stale", relevance=1.0, importance=1.0, published_time=stale_time)

    assert get_top_news(db_session, limit=10) == []


def test_get_top_news_excludes_unclassified_links(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    ticker_to_security_id = {s.ticker: s.id for s in db_session.scalars(select(Security))}
    # Provider-level match only (relevance set, importance/sentiment still NULL
    # until the LLM classification pass runs) — must not appear as "top news".
    store_articles(db_session, [_article("https://example.com/unclassified", matched=("AAPL",))], ticker_to_security_id)

    assert get_top_news(db_session, limit=10) == []


def test_get_top_news_attaches_realized_outcome_when_session_already_closed(db_session):
    # Regression: an article from earlier in the 48h lookback window can
    # already have a closed reacting session by the time /news/top is
    # requested — outcome attachment must not be skipped just because this
    # is the "today" view rather than history.
    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id

    published_time = datetime.now(timezone.utc) - timedelta(hours=30)
    prior_ts = published_time - timedelta(hours=4)
    reacting_ts = published_time + timedelta(hours=6)  # closed well within the 48h lookback

    db_session.add_all([
        _bar(aapl_id, prior_ts, 100.0), _bar(aapl_id, reacting_ts, 105.0),
        _bar(spy_id, prior_ts, 100.0), _bar(spy_id, reacting_ts, 101.0),
    ])
    db_session.commit()

    _classified_article(
        db_session, aapl_id, "https://example.com/already-closed",
        relevance=0.9, importance=0.9, sentiment=0.8, published_time=published_time,
    )

    item = get_top_news(db_session, limit=10)[0]

    assert item["actual_return"] == pytest.approx(0.05)
    assert item["benchmark_return"] == pytest.approx(0.01)
    assert item["direction_correct"] is True


def test_get_news_history_buckets_by_day_and_excludes_today(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    now = datetime.now(timezone.utc)
    today_midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    yesterday_ts = today_midnight - timedelta(hours=12)
    two_days_ago_ts = today_midnight - timedelta(days=2, hours=12)
    too_old_ts = today_midnight - timedelta(days=10)

    _classified_article(
        db_session, aapl_id, "https://example.com/yesterday", relevance=0.9, importance=0.9,
        published_time=yesterday_ts,
    )
    _classified_article(
        db_session, aapl_id, "https://example.com/two-days-ago", relevance=0.5, importance=0.5,
        published_time=two_days_ago_ts,
    )
    _classified_article(
        db_session, aapl_id, "https://example.com/today", relevance=1.0, importance=1.0,
        published_time=today_midnight + timedelta(hours=1),
    )
    _classified_article(
        db_session, aapl_id, "https://example.com/too-old", relevance=1.0, importance=1.0,
        published_time=too_old_ts,
    )

    history = get_news_history(db_session, days=7)

    dates = [day["date"] for day in history]
    assert two_days_ago_ts.date().isoformat() in dates
    assert yesterday_ts.date().isoformat() in dates
    assert today_midnight.date().isoformat() not in dates  # today excluded
    assert too_old_ts.date().isoformat() not in dates  # outside window
    # most recent day first
    assert dates == sorted(dates, reverse=True)


def test_get_news_history_caps_items_per_day(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    yesterday_noon = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)

    for i in range(8):
        _classified_article(
            db_session, aapl_id, f"https://example.com/day-{i}", relevance=0.5, importance=0.5 + i * 0.01,
            published_time=yesterday_noon,
        )

    history = get_news_history(db_session, days=7, per_day_limit=5)

    assert len(history) == 1
    assert len(history[0]["items"]) == 5
    # highest score first
    assert history[0]["items"][0]["score"] >= history[0]["items"][-1]["score"]


def _bar(security_id, ts, close):
    return MarketPrice(
        security_id=security_id, ts=ts, session_type="regular",
        open=close, high=close, low=close, close=close,
        volume=1_000_000, source="alpaca_iex",
    )


def test_get_news_history_attaches_realized_outcome_when_session_closed(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id

    published_time = datetime.now(timezone.utc) - timedelta(hours=26)
    prior_ts = published_time - timedelta(hours=4)
    reacting_ts = published_time + timedelta(hours=24)  # the next session's close, after publication

    db_session.add_all([
        _bar(aapl_id, prior_ts, 100.0), _bar(aapl_id, reacting_ts, 105.0),  # AAPL: +5%
        _bar(spy_id, prior_ts, 100.0), _bar(spy_id, reacting_ts, 101.0),  # SPY: +1%
    ])
    db_session.commit()

    _classified_article(
        db_session, aapl_id, "https://example.com/outcome-positive",
        relevance=0.9, importance=0.9, sentiment=0.8, published_time=published_time,
    )

    history = get_news_history(db_session, days=7)
    item = history[0]["items"][0]

    assert item["actual_return"] == pytest.approx(0.05)
    assert item["benchmark_return"] == pytest.approx(0.01)
    assert item["direction_correct"] is True  # positive sentiment, stock actually went up


def test_get_news_history_outcome_is_none_when_session_hasnt_closed_yet(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    # No MarketPrice bars at all after publication — nothing to react with yet.
    published_time = datetime.now(timezone.utc) - timedelta(hours=26)

    _classified_article(
        db_session, aapl_id, "https://example.com/outcome-pending",
        relevance=0.9, importance=0.9, sentiment=0.8, published_time=published_time,
    )

    history = get_news_history(db_session, days=7)
    item = history[0]["items"][0]

    assert item["actual_return"] is None
    assert item["benchmark_return"] is None
    assert item["direction_correct"] is None


def test_get_news_history_direction_correct_is_none_for_neutral_sentiment(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    seed_benchmarks(db_session)
    aapl_id = db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id
    spy_id = db_session.scalar(select(Security).where(Security.ticker == "SPY")).id

    published_time = datetime.now(timezone.utc) - timedelta(hours=26)
    prior_ts = published_time - timedelta(hours=4)
    reacting_ts = published_time + timedelta(hours=24)

    db_session.add_all([
        _bar(aapl_id, prior_ts, 100.0), _bar(aapl_id, reacting_ts, 105.0),
        _bar(spy_id, prior_ts, 100.0), _bar(spy_id, reacting_ts, 101.0),
    ])
    db_session.commit()

    _classified_article(
        db_session, aapl_id, "https://example.com/outcome-neutral",
        relevance=0.9, importance=0.9, sentiment=0.05, published_time=published_time,
    )

    history = get_news_history(db_session, days=7)
    item = history[0]["items"][0]

    assert item["actual_return"] == pytest.approx(0.05)  # outcome is still reported...
    assert item["direction_correct"] is None  # ...but no directional claim to grade
