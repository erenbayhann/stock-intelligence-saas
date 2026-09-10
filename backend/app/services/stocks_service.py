from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.fundamentals import Fundamentals
from app.models.market_price import MarketPrice
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.prediction import Prediction, PredictionResult, PredictionRun
from app.models.security import Security

DEFAULT_PRICE_RANGE_DAYS = 90


def get_security_by_ticker(db: Session, ticker: str) -> Security | None:
    return db.scalar(select(Security).where(Security.ticker == ticker.upper()))


def get_stock_detail(db: Session, ticker: str) -> dict | None:
    security = get_security_by_ticker(db, ticker)
    if security is None:
        return None
    company = db.get(Company, security.company_id)

    latest_prediction = db.scalar(
        select(Prediction)
        .join(PredictionRun, Prediction.prediction_run_id == PredictionRun.id)
        .where(
            Prediction.security_id == security.id,
            PredictionRun.run_type == "final",
            PredictionRun.target_session_date == date.today(),
        )
    )

    fundamentals_row = db.scalar(
        select(Fundamentals)
        .where(Fundamentals.security_id == security.id)
        .order_by(Fundamentals.filed_at.desc())
        .limit(1)
    )
    fundamentals = None
    if fundamentals_row is not None:
        fundamentals = {
            "period_end": fundamentals_row.period_end,
            "eps": float(fundamentals_row.eps) if fundamentals_row.eps is not None else None,
            "pe_ratio": float(fundamentals_row.pe_ratio) if fundamentals_row.pe_ratio is not None else None,
            "revenue_growth": float(fundamentals_row.revenue_growth) if fundamentals_row.revenue_growth is not None else None,
            "operating_margin": float(fundamentals_row.operating_margin) if fundamentals_row.operating_margin is not None else None,
            "market_cap": float(fundamentals_row.market_cap) if fundamentals_row.market_cap is not None else None,
            "dividend_yield": float(fundamentals_row.dividend_yield) if fundamentals_row.dividend_yield is not None else None,
        }

    return {
        "ticker": security.ticker,
        "company_name": company.name,
        "sector": company.sector,
        "current_rank": latest_prediction.rank if latest_prediction else None,
        "ai_score": float(latest_prediction.ai_score) if latest_prediction else None,
        "confidence": latest_prediction.confidence if latest_prediction else None,
        "explanation": latest_prediction.explanation if latest_prediction else None,
        "latest_fundamentals": fundamentals,
    }


def get_stock_prices(
    db: Session,
    ticker: str,
    from_date: date | None,
    to_date: date | None,
    session: str = "regular",
) -> dict | None:
    security = get_security_by_ticker(db, ticker)
    if security is None:
        return None

    to_date = to_date or date.today()
    from_date = from_date or (to_date - timedelta(days=DEFAULT_PRICE_RANGE_DAYS))

    query = select(MarketPrice).where(
        MarketPrice.security_id == security.id,
        MarketPrice.ts >= datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc),
        MarketPrice.ts <= datetime.combine(to_date, datetime.max.time(), tzinfo=timezone.utc),
    )
    if session != "all":
        query = query.where(MarketPrice.session_type == session)
    query = query.order_by(MarketPrice.ts)

    bars = db.scalars(query).all()
    return {
        "ticker": security.ticker,
        "bars": [
            {
                "ts": b.ts, "session_type": b.session_type,
                "open": float(b.open), "high": float(b.high), "low": float(b.low), "close": float(b.close),
                "volume": b.volume,
            }
            for b in bars
        ],
    }


def get_stock_news(db: Session, ticker: str, limit: int = 20) -> dict | None:
    security = get_security_by_ticker(db, ticker)
    if security is None:
        return None

    rows = db.scalars(
        select(NewsArticle)
        .join(NewsCompanyLink, NewsCompanyLink.news_article_id == NewsArticle.id)
        .where(NewsCompanyLink.security_id == security.id, NewsArticle.is_duplicate_of.is_(None))
        .order_by(NewsArticle.published_time.desc())
        .limit(limit)
    ).all()

    return {
        "ticker": security.ticker,
        "articles": [
            {
                "id": a.id, "title": a.title, "url": a.url, "source": a.source,
                "published_time": a.published_time,
                "sentiment": float(a.sentiment) if a.sentiment is not None else None,
                "event_category": a.event_category,
            }
            for a in rows
        ],
    }


def get_stock_predictions(db: Session, ticker: str, limit: int = 30) -> dict | None:
    """Only appears for days this ticker was actually in the top 5 — most
    days it won't have an entry, which is expected and correct (spec's
    api-and-schema-plan.md §1), not a bug.
    """
    security = get_security_by_ticker(db, ticker)
    if security is None:
        return None

    rows = db.execute(
        select(Prediction, PredictionResult, PredictionRun.target_session_date)
        .join(PredictionRun, Prediction.prediction_run_id == PredictionRun.id)
        .outerjoin(PredictionResult, PredictionResult.prediction_id == Prediction.id)
        .where(Prediction.security_id == security.id, PredictionRun.run_type == "final")
        .order_by(PredictionRun.target_session_date.desc())
        .limit(limit)
    ).all()

    return {
        "ticker": security.ticker,
        "predictions": [
            {
                "target_session_date": target_session_date,
                "rank": prediction.rank,
                "ai_score": float(prediction.ai_score),
                "confidence": prediction.confidence,
                "actual_return": float(result.actual_return) if result and result.actual_return is not None else None,
                "direction_correct": result.direction_correct if result else None,
            }
            for prediction, result, target_session_date in rows
        ],
    }
