import logging
import statistics
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.feature_snapshot import FeatureSnapshot
from app.models.fundamentals import Fundamentals
from app.models.macro import MacroData
from app.models.market_price import MarketPrice
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.security import Security
from app.providers.macro.fred import DEFAULT_SERIES

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "SPY"
_POSITIVE_SENTIMENT_THRESHOLD = 0.2
_NEGATIVE_SENTIMENT_THRESHOLD = -0.2


def _closes_and_volumes(db: Session, security_id: int, as_of: datetime, limit: int) -> list[tuple]:
    """Regular-session bars at or before as_of, most recent first — the
    single point-in-time gate for every market feature below. A bar dated
    after as_of must never appear here (spec §3).
    """
    rows = db.execute(
        select(MarketPrice.ts, MarketPrice.close, MarketPrice.volume)
        .where(
            MarketPrice.security_id == security_id,
            MarketPrice.session_type == "regular",
            MarketPrice.ts <= as_of,
        )
        .order_by(MarketPrice.ts.desc())
        .limit(limit)
    ).all()
    return rows


def _return_over(bars: list[tuple], n: int) -> float | None:
    if len(bars) <= n:
        return None
    latest = float(bars[0].close)
    prior = float(bars[n].close)
    if prior == 0:
        return None
    return (latest - prior) / prior


def compute_market_features(db: Session, security_id: int, as_of: datetime) -> dict:
    bars = _closes_and_volumes(db, security_id, as_of, limit=61)
    if not bars:
        return {}

    features: dict = {
        "return_1d": _return_over(bars, 1),
        "return_5d": _return_over(bars, 5),
        "return_20d": _return_over(bars, 20),
        "return_60d": _return_over(bars, 60),
        "volume": int(bars[0].volume),
    }

    if len(bars) >= 2 and bars[1].volume:
        features["volume_change"] = float(bars[0].volume) / float(bars[1].volume) - 1
    else:
        features["volume_change"] = None

    window20 = bars[:20]
    if len(window20) == 20:
        avg_vol_20d = statistics.mean(float(b.volume) for b in window20)
        features["relative_volume"] = float(bars[0].volume) / avg_vol_20d if avg_vol_20d else None
        features["moving_avg_20d"] = statistics.mean(float(b.close) for b in window20)
        daily_returns = [
            (float(window20[i].close) - float(window20[i + 1].close)) / float(window20[i + 1].close)
            for i in range(len(window20) - 1)
            if float(window20[i + 1].close) != 0
        ]
        features["realized_volatility_20d"] = statistics.pstdev(daily_returns) if len(daily_returns) >= 2 else None
    else:
        features["relative_volume"] = None
        features["moving_avg_20d"] = None
        features["realized_volatility_20d"] = None

    window50 = bars[:50]
    features["moving_avg_50d"] = statistics.mean(float(b.close) for b in window50) if len(window50) == 50 else None

    return features


def compute_benchmark_features(db: Session, as_of: datetime) -> tuple[dict, float | None]:
    """Returns (benchmark_return_features, benchmark_return_20d) — the raw
    20d return is also handed back so callers can compute relative_strength
    without a second lookup.
    """
    benchmark = db.scalar(select(Security).where(Security.ticker == BENCHMARK_TICKER))
    if benchmark is None:
        return {}, None
    bars = _closes_and_volumes(db, benchmark.id, as_of, limit=21)
    features = {
        "benchmark_return_1d": _return_over(bars, 1),
        "benchmark_return_5d": _return_over(bars, 5),
        "benchmark_return_20d": _return_over(bars, 20),
    }
    return features, features["benchmark_return_20d"]


def compute_sector_peer_returns_20d(db: Session, as_of: datetime, universe_tickers: set[str]) -> dict[str, float]:
    """20-day return per sector, averaged across universe peers only (spec
    §6's "sector performance" — approximated from our own S&P 100 universe
    rather than fetching separate sector ETF data, per spec §27's
    correctness-over-complexity principle).
    """
    securities = db.execute(
        select(Security.id, Security.ticker, Company.sector)
        .join(Company, Security.company_id == Company.id)
        .where(Security.ticker.in_(universe_tickers))
    ).all()

    returns_by_sector: dict[str, list[float]] = {}
    for security_id, ticker, sector in securities:
        if not sector:
            continue
        bars = _closes_and_volumes(db, security_id, as_of, limit=21)
        r = _return_over(bars, 20)
        if r is not None:
            returns_by_sector.setdefault(sector, []).append(r)

    return {sector: statistics.mean(values) for sector, values in returns_by_sector.items() if values}


def compute_fundamental_features(db: Session, security_id: int, as_of: datetime) -> dict:
    """Latest fundamentals row with filed_at <= as_of — the point-in-time
    gate. A fundamentals row filed after as_of must never be used (spec §3).
    """
    row = db.scalar(
        select(Fundamentals)
        .where(Fundamentals.security_id == security_id, Fundamentals.filed_at <= as_of)
        .order_by(Fundamentals.filed_at.desc())
        .limit(1)
    )
    if row is None:
        return {}
    return {
        "revenue_growth": float(row.revenue_growth) if row.revenue_growth is not None else None,
        "earnings_growth": float(row.earnings_growth) if row.earnings_growth is not None else None,
        "eps": float(row.eps) if row.eps is not None else None,
        "pe_ratio": float(row.pe_ratio) if row.pe_ratio is not None else None,
        "price_to_book": float(row.price_to_book) if row.price_to_book is not None else None,
        "ev_ebitda": float(row.ev_ebitda) if row.ev_ebitda is not None else None,
        "debt_equity": float(row.debt_equity) if row.debt_equity is not None else None,
        "net_debt_ebitda": float(row.net_debt_ebitda) if row.net_debt_ebitda is not None else None,
        "roe": float(row.roe) if row.roe is not None else None,
        "operating_margin": float(row.operating_margin) if row.operating_margin is not None else None,
        "free_cash_flow": float(row.free_cash_flow) if row.free_cash_flow is not None else None,
        "market_cap": float(row.market_cap) if row.market_cap is not None else None,
        "dividend_yield": float(row.dividend_yield) if row.dividend_yield is not None else None,
    }


def compute_macro_features(db: Session, as_of: datetime) -> dict:
    """Latest value per series with realtime_start <= as_of — the
    point-in-time gate for macro data (spec §3/§4; see also the vintage
    caveat documented in app/providers/macro/fred.py).
    """
    features = {}
    for series_id in DEFAULT_SERIES:
        row = db.scalar(
            select(MacroData)
            .where(MacroData.series_id == series_id, MacroData.realtime_start <= as_of)
            .order_by(MacroData.observation_date.desc(), MacroData.realtime_start.desc())
            .limit(1)
        )
        features[f"macro_{series_id.lower()}"] = float(row.value) if row else None
    return features


def compute_news_features(db: Session, security_id: int, as_of: datetime) -> dict:
    """Only news with published_time <= as_of may ever contribute — this is
    the single most safety-critical point-in-time gate in the whole feature
    set (spec §3: "News published after a prediction must never appear in
    that prediction's feature set").
    """
    window_24h = as_of - timedelta(hours=24)
    window_72h = as_of - timedelta(hours=72)

    articles_72h = db.execute(
        select(NewsArticle.sentiment, NewsArticle.importance, NewsArticle.event_category, NewsArticle.published_time)
        .join(NewsCompanyLink, NewsCompanyLink.news_article_id == NewsArticle.id)
        .where(
            NewsCompanyLink.security_id == security_id,
            NewsArticle.published_time <= as_of,
            NewsArticle.published_time >= window_72h,
            NewsArticle.is_duplicate_of.is_(None),
        )
    ).all()

    articles_24h = [a for a in articles_72h if a.published_time >= window_24h]
    sentiments_24h = [float(a.sentiment) for a in articles_24h if a.sentiment is not None]

    return {
        "news_sentiment_24h": statistics.mean(sentiments_24h) if sentiments_24h else None,
        "news_importance_24h": (
            statistics.mean(float(a.importance) for a in articles_24h if a.importance is not None)
            if any(a.importance is not None for a in articles_24h)
            else None
        ),
        "positive_news_24h": sum(1 for s in sentiments_24h if s > _POSITIVE_SENTIMENT_THRESHOLD),
        "negative_news_24h": sum(1 for s in sentiments_24h if s < _NEGATIVE_SENTIMENT_THRESHOLD),
        "earnings_event_72h": int(any(a.event_category == "Earnings" for a in articles_72h)),
        "analyst_upgrade_72h": int(
            any(a.event_category == "Analyst upgrade/downgrade" for a in articles_72h)
        ),
    }


def generate_feature_snapshot(
    db: Session,
    security_id: int,
    sector: str | None,
    as_of: datetime,
    benchmark_features: dict,
    benchmark_return_20d: float | None,
    sector_peer_returns_20d: dict[str, float],
) -> FeatureSnapshot:
    features: dict = {}
    features.update(compute_market_features(db, security_id, as_of))
    features.update(benchmark_features)
    features.update(compute_fundamental_features(db, security_id, as_of))
    features.update(compute_macro_features(db, as_of))
    features.update(compute_news_features(db, security_id, as_of))

    security_return_20d = features.get("return_20d")
    features["relative_strength_20d"] = (
        security_return_20d - benchmark_return_20d
        if security_return_20d is not None and benchmark_return_20d is not None
        else None
    )
    sector_avg = sector_peer_returns_20d.get(sector) if sector else None
    features["sector_relative_performance_20d"] = (
        security_return_20d - sector_avg if security_return_20d is not None and sector_avg is not None else None
    )

    snapshot = FeatureSnapshot(security_id=security_id, as_of=as_of, features=features)
    db.add(snapshot)
    return snapshot
