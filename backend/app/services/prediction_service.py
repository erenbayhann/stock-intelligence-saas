import logging
from datetime import date, datetime, timedelta, timezone

import joblib
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.dataset import FEATURE_COLUMNS
from app.ml.explain import explain_prediction
from app.ml.train import ARTIFACT_DIR
from app.models.company import Company
from app.models.market_price import MarketPrice
from app.models.model_version import ModelVersion
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.prediction import Prediction, PredictionNewsLink, PredictionRun
from app.models.security import Security
from app.services.feature_service import (
    compute_benchmark_features,
    compute_macro_features,
    compute_sector_peer_returns_20d,
    generate_feature_snapshot,
)

logger = logging.getLogger(__name__)

TOP_N = 5
CONFIDENCE_HIGH_Z = 1.5
CONFIDENCE_MEDIUM_Z = 0.75
NEWS_LOOKBACK_HOURS = 72


class NoChampionModelError(Exception):
    pass


class PredictionAlreadyExistsError(Exception):
    pass


def _load_champion(db: Session) -> tuple[ModelVersion, object]:
    champion = db.scalar(select(ModelVersion).where(ModelVersion.status == "champion"))
    if champion is None:
        raise NoChampionModelError("No champion model_version exists — run app.jobs.train_model first")
    artifact_path = ARTIFACT_DIR / f"{champion.version_label}.joblib"
    if not artifact_path.exists():
        raise NoChampionModelError(f"Champion model artifact missing on disk: {artifact_path}")
    pipeline = joblib.load(artifact_path)
    return champion, pipeline


def _confidence_from_z(z: float) -> str:
    if z >= CONFIDENCE_HIGH_Z:
        return "High"
    if z >= CONFIDENCE_MEDIUM_Z:
        return "Medium"
    return "Low"


def generate_final_prediction_run(
    db: Session, universe_tickers: set[str], target_session_date: date | None = None
) -> dict:
    """spec §6/§11: scores every S&P 100 security with the current champion,
    locks the top 5 into an immutable prediction_runs/predictions snapshot.
    Idempotent per spec §17's unique partial index (one 'final' run per
    target_session_date) — checked explicitly here so a re-run reports
    clearly rather than surfacing a raw DB constraint error.
    """
    target_session_date = target_session_date or datetime.now(timezone.utc).date()

    existing = db.scalar(
        select(PredictionRun).where(
            PredictionRun.target_session_date == target_session_date,
            PredictionRun.run_type == "final",
        )
    )
    if existing is not None:
        raise PredictionAlreadyExistsError(
            f"A final prediction run already exists for {target_session_date} (id={existing.id})"
        )

    champion, pipeline = _load_champion(db)

    as_of = datetime.now(timezone.utc)
    securities = db.execute(
        select(Security.id, Security.ticker, Company.sector, Company.name)
        .join(Company, Security.company_id == Company.id)
        .where(Security.is_active.is_(True), Security.ticker.in_(universe_tickers))
    ).all()

    benchmark_features, benchmark_return_20d = compute_benchmark_features(db, as_of)
    sector_peer_returns_20d = compute_sector_peer_returns_20d(db, as_of, universe_tickers)
    macro_features = compute_macro_features(db, as_of)

    snapshots = {}
    for security_id, ticker, sector, name in securities:
        snapshot = generate_feature_snapshot(
            db, security_id, sector,
            market_as_of=as_of, intraday_as_of=as_of,
            benchmark_features=benchmark_features,
            benchmark_return_20d=benchmark_return_20d,
            sector_peer_returns_20d=sector_peer_returns_20d,
            macro_features=macro_features,
            snapshot_as_of=as_of,
        )
        snapshots[security_id] = snapshot
    db.flush()  # populate snapshot.id for every snapshot

    cohort_df = pd.DataFrame(
        {sid: {col: snap.features.get(col) for col in FEATURE_COLUMNS} for sid, snap in snapshots.items()}
    ).T

    predicted = pipeline.predict(cohort_df[FEATURE_COLUMNS])
    cohort_df["predicted_excess_return"] = predicted
    cohort_df["ai_score"] = cohort_df["predicted_excess_return"].rank(pct=True) * 100

    mean_pred = cohort_df["predicted_excess_return"].mean()
    std_pred = cohort_df["predicted_excess_return"].std()

    ticker_by_id = {s.id: s.ticker for s in securities}
    name_by_id = {s.id: s.name for s in securities}

    top5_ids = cohort_df["predicted_excess_return"].nlargest(TOP_N).index.tolist()

    prediction_run = PredictionRun(
        generated_at=as_of,
        model_version_id=champion.id,
        run_type="final",
        target_session_date=target_session_date,
        status="completed",
    )
    db.add(prediction_run)
    db.flush()

    news_since = as_of - timedelta(hours=NEWS_LOOKBACK_HOURS)
    predictions_created = []

    for rank, security_id in enumerate(top5_ids, start=1):
        row = cohort_df.loc[security_id]
        z = (row["predicted_excess_return"] - mean_pred) / std_pred if std_pred else 0.0
        confidence = _confidence_from_z(z)

        price = db.scalar(
            select(MarketPrice.close)
            .where(
                MarketPrice.security_id == security_id,
                MarketPrice.session_type == "regular",
                MarketPrice.ts <= as_of,
            )
            .order_by(MarketPrice.ts.desc())
            .limit(1)
        )
        if price is None:
            # Never fabricate a price (spec §27) — a top-5 candidate with no
            # market data at all indicates a real data problem, not something
            # to paper over with a 0.
            raise ValueError(f"No market price available for security_id={security_id} at {as_of}")

        explanation = explain_prediction(
            pipeline, snapshots[security_id].features, cohort_df[FEATURE_COLUMNS]
        )

        prediction = Prediction(
            prediction_run_id=prediction_run.id,
            security_id=security_id,
            rank=rank,
            ai_score=round(float(row["ai_score"]), 2),
            raw_predicted_excess_return=round(float(row["predicted_excess_return"]), 5),
            confidence=confidence,
            explanation=explanation,
            feature_snapshot_id=snapshots[security_id].id,
            price_at_prediction=price,
        )
        db.add(prediction)
        db.flush()

        recent_news = db.scalars(
            select(NewsArticle.id)
            .join(NewsCompanyLink, NewsCompanyLink.news_article_id == NewsArticle.id)
            .where(
                NewsCompanyLink.security_id == security_id,
                NewsArticle.published_time >= news_since,
                NewsArticle.published_time <= as_of,
                NewsArticle.is_duplicate_of.is_(None),
            )
        ).all()
        for news_article_id in recent_news:
            db.add(PredictionNewsLink(prediction_id=prediction.id, news_article_id=news_article_id))

        predictions_created.append({
            "rank": rank,
            "ticker": ticker_by_id[security_id],
            "name": name_by_id[security_id],
            "ai_score": prediction.ai_score,
            "confidence": confidence,
        })

    db.commit()
    return {
        "prediction_run_id": prediction_run.id,
        "model_version_id": champion.id,
        "model_version_label": champion.version_label,
        "target_session_date": target_session_date.isoformat(),
        "candidates_scored": len(securities),
        "top5": predictions_created,
    }
