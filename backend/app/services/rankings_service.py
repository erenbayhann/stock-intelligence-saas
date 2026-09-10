from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.model_version import ModelVersion
from app.models.news import NewsArticle
from app.models.prediction import Prediction, PredictionNewsLink, PredictionResult, PredictionRun
from app.models.security import Security


def _news_for_prediction(db: Session, prediction_id: int) -> list[dict]:
    rows = db.execute(
        select(NewsArticle)
        .join(PredictionNewsLink, PredictionNewsLink.news_article_id == NewsArticle.id)
        .where(PredictionNewsLink.prediction_id == prediction_id)
        .order_by(NewsArticle.published_time.desc())
    ).scalars().all()
    return [
        {"id": a.id, "title": a.title, "url": a.url, "source": a.source, "published_time": a.published_time}
        for a in rows
    ]


def _prediction_rows(db: Session, prediction_run_id: int):
    return db.execute(
        select(Prediction, Security.ticker, Company.name)
        .join(Security, Prediction.security_id == Security.id)
        .join(Company, Security.company_id == Company.id)
        .where(Prediction.prediction_run_id == prediction_run_id)
        .order_by(Prediction.rank)
    ).all()


def get_latest_ranking(db: Session) -> dict | None:
    """spec §1/§13: never includes actual_return/benchmark_return — those
    structurally don't exist yet for a still-open/just-locked prediction.
    """
    run = db.scalar(
        select(PredictionRun)
        .where(PredictionRun.run_type == "final")
        .order_by(PredictionRun.generated_at.desc())
        .limit(1)
    )
    if run is None:
        return None

    model_version = db.get(ModelVersion, run.model_version_id)
    top5 = [
        {
            "rank": prediction.rank,
            "ticker": ticker,
            "company_name": name,
            "ai_score": float(prediction.ai_score),
            "confidence": prediction.confidence,
            "explanation": prediction.explanation,
            "related_news": _news_for_prediction(db, prediction.id),
        }
        for prediction, ticker, name in _prediction_rows(db, run.id)
    ]
    return {
        "generated_at": run.generated_at,
        "model_version": model_version.version_label,
        "top5": top5,
    }


def get_ranking_for_date(db: Session, target_session_date: date) -> dict | None:
    run = db.scalar(
        select(PredictionRun).where(
            PredictionRun.run_type == "final",
            PredictionRun.target_session_date == target_session_date,
        )
    )
    if run is None:
        return None

    model_version = db.get(ModelVersion, run.model_version_id)
    top5 = []
    benchmark_return = None
    correct_count = 0
    evaluated_count = 0
    notable_news: dict[int, dict] = {}

    for prediction, ticker, name in _prediction_rows(db, run.id):
        result = db.scalar(select(PredictionResult).where(PredictionResult.prediction_id == prediction.id))
        item = {
            "rank": prediction.rank,
            "ticker": ticker,
            "company_name": name,
            "ai_score": float(prediction.ai_score),
            "confidence": prediction.confidence,
            "explanation": prediction.explanation,
            "related_news": _news_for_prediction(db, prediction.id),
            "actual_return": None,
            "benchmark_return": None,
            "vs_benchmark": None,
            "direction_correct": None,
        }
        if result is not None and result.evaluated_at is not None:
            item["actual_return"] = float(result.actual_return)
            item["benchmark_return"] = float(result.benchmark_return)
            item["vs_benchmark"] = float(result.actual_excess_return)
            item["direction_correct"] = result.direction_correct
            benchmark_return = float(result.benchmark_return)
            evaluated_count += 1
            if result.direction_correct:
                correct_count += 1
        top5.append(item)
        for news in item["related_news"]:
            notable_news[news["id"]] = news

    return {
        "target_session_date": run.target_session_date,
        "generated_at": run.generated_at,
        "model_version": model_version.version_label,
        "benchmark_return": benchmark_return,
        "hit_rate": (correct_count / evaluated_count) if evaluated_count else None,
        "top5": top5,
        "notable_news": sorted(notable_news.values(), key=lambda n: n["published_time"], reverse=True),
    }


def get_ranking_history(db: Session, limit: int = 7, before: date | None = None) -> list[dict]:
    """Lightweight per-day summary (spec's api-and-schema-plan.md §1) — the
    full detail is fetched separately via get_ranking_for_date when a day
    is opened, never eagerly here.
    """
    query = select(PredictionRun).where(PredictionRun.run_type == "final")
    if before is not None:
        query = query.where(PredictionRun.target_session_date < before)
    runs = db.scalars(query.order_by(PredictionRun.target_session_date.desc()).limit(limit)).all()

    items = []
    for run in runs:
        results = db.execute(
            select(PredictionResult)
            .join(Prediction, PredictionResult.prediction_id == Prediction.id)
            .where(Prediction.prediction_run_id == run.id, PredictionResult.evaluated_at.is_not(None))
        ).scalars().all()

        hit_rate = None
        mean_excess_return = None
        if results:
            hit_rate = sum(1 for r in results if r.direction_correct) / len(results)
            mean_excess_return = sum(float(r.actual_excess_return) for r in results) / len(results)

        items.append({
            "target_session_date": run.target_session_date,
            "hit_rate": hit_rate,
            "mean_excess_return": mean_excess_return,
        })
    return items
