from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.fundamentals import Fundamentals
from app.models.macro import MacroData
from app.models.market_price import MarketPrice
from app.models.news import NewsArticle, NewsCompanyLink
from app.services.feature_service import (
    compute_fundamental_features,
    compute_macro_features,
    compute_market_features,
    compute_news_features,
)
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]

AS_OF = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)


def _security_id(db):
    seed_universe(db, SAMPLE_UNIVERSE)
    from sqlalchemy import select

    from app.models.security import Security

    return db.scalar(select(Security).where(Security.ticker == "AAPL")).id


def _add_bar(db, security_id, ts, close, volume=1_000_000):
    db.add(
        MarketPrice(
            security_id=security_id,
            ts=ts,
            session_type="regular",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=volume,
            source="alpaca_iex",
        )
    )


def test_market_features_never_use_a_bar_after_as_of(db_session):
    security_id = _security_id(db_session)
    _add_bar(db_session, security_id, AS_OF - timedelta(days=1), close=100.0)
    # A bar dated AFTER as_of with a wildly different price — if this ever
    # leaks in, return_1d would reflect it instead of staying based on the
    # last bar at/before as_of.
    _add_bar(db_session, security_id, AS_OF + timedelta(days=1), close=99999.0)
    db_session.commit()

    features = compute_market_features(db_session, security_id, AS_OF)

    assert features["volume"] == 1_000_000
    # only one bar at/before as_of exists, so return_1d (needs 2 bars) is None
    assert features["return_1d"] is None


def test_market_features_use_the_latest_bar_at_or_before_as_of(db_session):
    security_id = _security_id(db_session)
    _add_bar(db_session, security_id, AS_OF - timedelta(days=2), close=100.0)
    _add_bar(db_session, security_id, AS_OF - timedelta(days=1), close=110.0)
    _add_bar(db_session, security_id, AS_OF + timedelta(days=1), close=1.0)  # future — must be ignored
    db_session.commit()

    features = compute_market_features(db_session, security_id, AS_OF)

    # latest-at-or-before-as_of is the 110.0 bar; 1-day return vs the 100.0 bar
    assert features["return_1d"] == pytest.approx((110.0 - 100.0) / 100.0)


def test_fundamentals_filed_after_as_of_are_excluded(db_session):
    security_id = _security_id(db_session)
    db_session.add(
        Fundamentals(
            security_id=security_id,
            period_end=date(2026, 3, 31),
            filed_at=AS_OF - timedelta(days=10),
            source="sec_edgar",
            eps=1.50,
        )
    )
    # Filed AFTER as_of — a real point-in-time leak if this ever gets used.
    db_session.add(
        Fundamentals(
            security_id=security_id,
            period_end=date(2026, 6, 30),
            filed_at=AS_OF + timedelta(days=5),
            source="sec_edgar",
            eps=999.0,
        )
    )
    db_session.commit()

    features = compute_fundamental_features(db_session, security_id, AS_OF)

    assert features["eps"] == 1.50


def test_macro_data_with_future_realtime_start_is_excluded(db_session):
    from app.providers.macro.fred import DEFAULT_SERIES

    series_id = DEFAULT_SERIES[0]
    db_session.add(
        MacroData(
            series_id=series_id,
            observation_date=date(2026, 6, 1),
            value=4.5,
            realtime_start=AS_OF.date() - timedelta(days=1),
            realtime_end=date(9999, 12, 31),
            source="fred",
        )
    )
    # A later revision "known" only after as_of — must not be used.
    db_session.add(
        MacroData(
            series_id=series_id,
            observation_date=date(2026, 6, 1),
            value=999.0,
            realtime_start=AS_OF.date() + timedelta(days=2),
            realtime_end=date(9999, 12, 31),
            source="fred",
        )
    )
    db_session.commit()

    features = compute_macro_features(db_session, AS_OF)

    assert features[f"macro_{series_id.lower()}"] == 4.5


def test_news_published_after_as_of_never_contributes(db_session):
    security_id = _security_id(db_session)

    old_article = NewsArticle(
        source="gdelt",
        title="Old news",
        url="https://x.com/old",
        published_time=AS_OF - timedelta(hours=1),
        sentiment=0.5,
        importance=0.5,
        event_category="Earnings",
    )
    future_article = NewsArticle(
        source="gdelt",
        title="Future news that must not leak backward",
        url="https://x.com/future",
        published_time=AS_OF + timedelta(hours=1),
        sentiment=-0.9,  # if this leaked in, news_sentiment_24h would swing negative
        importance=0.9,
        event_category="Lawsuit",
    )
    db_session.add_all([old_article, future_article])
    db_session.flush()
    db_session.add(NewsCompanyLink(news_article_id=old_article.id, security_id=security_id, relevance=1.0))
    db_session.add(NewsCompanyLink(news_article_id=future_article.id, security_id=security_id, relevance=1.0))
    db_session.commit()

    features = compute_news_features(db_session, security_id, AS_OF)

    assert features["news_sentiment_24h"] == 0.5
    assert features["positive_news_24h"] == 1
    assert features["negative_news_24h"] == 0
    assert features["earnings_event_72h"] == 1  # from the old article only


def test_news_duplicate_articles_are_excluded_from_features(db_session):
    security_id = _security_id(db_session)

    original = NewsArticle(
        source="gdelt",
        title="Original story",
        url="https://x.com/orig",
        published_time=AS_OF - timedelta(hours=2),
        sentiment=0.6,
        importance=0.6,
    )
    db_session.add(original)
    db_session.flush()

    duplicate = NewsArticle(
        source="marketaux",
        title="Same story, different outlet",
        url="https://x.com/dup",
        published_time=AS_OF - timedelta(hours=1),
        sentiment=0.6,
        importance=0.6,
        is_duplicate_of=original.id,
    )
    db_session.add(duplicate)
    db_session.flush()

    db_session.add(NewsCompanyLink(news_article_id=original.id, security_id=security_id, relevance=1.0))
    db_session.add(NewsCompanyLink(news_article_id=duplicate.id, security_id=security_id, relevance=1.0))
    db_session.commit()

    features = compute_news_features(db_session, security_id, AS_OF)

    # spec §5: a republished wire story must not count as two independent signals
    assert features["positive_news_24h"] == 1
