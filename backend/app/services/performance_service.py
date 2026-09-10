from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.evaluate import simulate_top5_portfolio
from app.models.prediction import Prediction, PredictionResult, PredictionRun

VALID_WINDOWS = {"7d", "30d", "all"}


def compute_performance_summary(
    db: Session, window: str = "7d", model_version_id: int | None = None
) -> dict:
    """spec §14/api-and-schema-plan.md §1: aggregate metrics computed ONLY
    from prediction_results rows with evaluated_at IS NOT NULL — a live,
    still-open prediction has no result row at all yet (spec §13), so the
    inner join here structurally excludes it; there's no flag to forget.
    """
    if window not in VALID_WINDOWS:
        raise ValueError(f"Unknown window: {window!r} (expected one of {VALID_WINDOWS})")

    query = (
        select(
            Prediction.rank,
            Prediction.raw_predicted_excess_return,
            PredictionResult.actual_return,
            PredictionResult.benchmark_return,
            PredictionResult.actual_excess_return,
            PredictionResult.direction_correct,
            PredictionRun.target_session_date,
        )
        .join(PredictionRun, Prediction.prediction_run_id == PredictionRun.id)
        .join(PredictionResult, PredictionResult.prediction_id == Prediction.id)
        .where(PredictionResult.evaluated_at.is_not(None))
    )
    if model_version_id is not None:
        query = query.where(PredictionRun.model_version_id == model_version_id)
    if window == "7d":
        query = query.where(PredictionRun.target_session_date >= date.today() - timedelta(days=7))
    elif window == "30d":
        query = query.where(PredictionRun.target_session_date >= date.today() - timedelta(days=30))

    rows = db.execute(query).all()
    if not rows:
        return {"window": window, "n_predictions": 0, "n_days": 0}

    df = pd.DataFrame(
        rows,
        columns=[
            "rank", "predicted", "actual_return", "benchmark_return",
            "actual_excess_return", "direction_correct", "target_session_date",
        ],
    )
    for col in ("predicted", "actual_return", "benchmark_return", "actual_excess_return"):
        df[col] = df[col].astype(float)

    daily_rank_ic = []
    for _, day_df in df.groupby("target_session_date"):
        if len(day_df) >= 2:
            corr, _ = spearmanr(day_df["predicted"], day_df["actual_excess_return"])
            if not np.isnan(corr):
                daily_rank_ic.append(corr)

    hit_rate = float(df["direction_correct"].mean())
    portfolio = simulate_top5_portfolio(df, "predicted")

    return {
        "window": window,
        "n_predictions": int(len(df)),
        "n_days": int(df["target_session_date"].nunique()),
        "hit_rate": hit_rate,
        "directional_accuracy": hit_rate,
        "mean_actual_return": float(df["actual_return"].mean()),
        "mean_excess_return": float(df["actual_excess_return"].mean()),
        "mean_benchmark_return": float(df["benchmark_return"].mean()),
        "mae": float((df["predicted"] - df["actual_excess_return"]).abs().mean()),
        "rmse": float(((df["predicted"] - df["actual_excess_return"]) ** 2).mean() ** 0.5),
        "mean_rank_ic": float(np.mean(daily_rank_ic)) if daily_rank_ic else None,
        "hypothetical_portfolio": portfolio or None,
    }
