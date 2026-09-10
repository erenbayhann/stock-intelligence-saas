from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_db
from app.main import app
from app.models.fundamentals import Fundamentals
from app.models.market_price import MarketPrice
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.security import Security
from app.services.universe_service import seed_universe

SAMPLE_UNIVERSE = [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "exchange": "NASDAQ", "cik": "0000320193"},
]


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _security_id(db_session):
    seed_universe(db_session, SAMPLE_UNIVERSE)
    return db_session.scalar(select(Security).where(Security.ticker == "AAPL")).id


def test_stock_detail_returns_404_for_unknown_ticker(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/stocks/ZZZZ")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_stock_detail_includes_latest_fundamentals(db_session):
    security_id = _security_id(db_session)
    db_session.add(Fundamentals(
        security_id=security_id, period_end=date(2026, 6, 30), filed_at=datetime.now(timezone.utc),
        source="sec_edgar_xbrl", eps=1.5, pe_ratio=28.0, revenue_growth=0.08,
        operating_margin=0.3, market_cap=3_000_000_000_000, dividend_yield=0.005,
    ))
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/stocks/aapl")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["company_name"] == "Apple Inc."
    assert body["latest_fundamentals"]["eps"] == 1.5


def test_stock_prices_defaults_to_regular_session_and_90_day_range(db_session):
    security_id = _security_id(db_session)
    today = datetime.now(timezone.utc)
    db_session.add(MarketPrice(
        security_id=security_id, ts=today, session_type="regular",
        open=100.0, high=101.0, low=99.0, close=100.5, volume=1_000_000, source="alpaca_iex",
    ))
    db_session.add(MarketPrice(
        security_id=security_id, ts=today, session_type="pre",
        open=99.0, high=99.5, low=98.5, close=99.2, volume=10_000, source="alpaca_iex",
    ))
    db_session.add(MarketPrice(
        security_id=security_id, ts=today - timedelta(days=200), session_type="regular",
        open=90.0, high=91.0, low=89.0, close=90.5, volume=500_000, source="alpaca_iex",
    ))
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/stocks/AAPL/prices")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    bars = response.json()["bars"]
    assert len(bars) == 1
    assert bars[0]["session_type"] == "regular"
    assert bars[0]["close"] == 100.5


def test_stock_prices_session_all_includes_every_session_type(db_session):
    security_id = _security_id(db_session)
    today = datetime.now(timezone.utc)
    db_session.add(MarketPrice(
        security_id=security_id, ts=today, session_type="regular",
        open=100.0, high=101.0, low=99.0, close=100.5, volume=1_000_000, source="alpaca_iex",
    ))
    db_session.add(MarketPrice(
        security_id=security_id, ts=today, session_type="pre",
        open=99.0, high=99.5, low=98.5, close=99.2, volume=10_000, source="alpaca_iex",
    ))
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/stocks/AAPL/prices?session=all")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()["bars"]) == 2


def test_stock_news_excludes_duplicates(db_session):
    security_id = _security_id(db_session)
    original = NewsArticle(
        source="marketaux", title="Apple launches new product", url="https://example.com/1",
        published_time=datetime.now(timezone.utc), sentiment=0.4, event_category="product_launch",
    )
    db_session.add(original)
    db_session.flush()
    duplicate = NewsArticle(
        source="gdelt", title="Apple launches new product (wire)", url="https://example.com/2",
        published_time=datetime.now(timezone.utc), is_duplicate_of=original.id,
    )
    db_session.add(duplicate)
    db_session.flush()
    db_session.add(NewsCompanyLink(news_article_id=original.id, security_id=security_id))
    db_session.add(NewsCompanyLink(news_article_id=duplicate.id, security_id=security_id))
    db_session.commit()

    client = _client(db_session)
    try:
        response = client.get("/api/v1/stocks/AAPL/news")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    articles = response.json()["articles"]
    assert len(articles) == 1
    assert articles[0]["title"] == "Apple launches new product"


def test_stock_predictions_returns_404_for_unknown_ticker(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/stocks/ZZZZ/predictions")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
