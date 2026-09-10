import logging
from datetime import date, datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from app.ml.dataset import FEATURE_COLUMNS, FEATURE_SET_LABEL, LABEL_COLUMN, load_dataset
from app.ml.evaluate import evaluate_predictions, simulate_top5_portfolio
from app.models.model_version import ModelVersion
from app.models.training_run import TrainingRun

logger = logging.getLogger(__name__)

# spec §12: exponential recency weighting, grounded in MSCI/Barra USE4's
# 84-504 trading-day range for equity risk factors — 252 (~1 year) chosen as
# the more reactive end since staying visibly responsive matters more for a
# single-owner MVP than for an institutional risk desk.
RECENCY_HALFLIFE_DAYS = 252

TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
# remaining ~0.15 is the held-out test window

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml_artifacts"


def compute_sample_weights(dates: pd.Series, halflife_days: int = RECENCY_HALFLIFE_DAYS) -> np.ndarray:
    """weight = exp(-age_in_days / halflife) — age measured from the
    training set's OWN most recent date, not "today", so weighting is
    reproducible regardless of when training is re-run (spec §12).
    """
    most_recent = dates.max()
    age_days = (most_recent - dates).apply(lambda d: d.days)
    return np.exp(-age_days / halflife_days).to_numpy()


def chronological_split(
    df: pd.DataFrame,
    train_fraction: float = TRAIN_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Splits by DATE boundary, never by row count — splitting mid-date would
    put some of a single day's ~100 cross-sectionally-correlated securities
    in train and others in validation, leaking that day's shared macro/
    sector conditions across the split. Never shuffled (spec §21).
    """
    unique_dates = sorted(df["target_session_date"].unique())
    n = len(unique_dates)
    train_end = unique_dates[int(n * train_fraction) - 1]
    val_end = unique_dates[int(n * (train_fraction + validation_fraction)) - 1]

    train = df[df["target_session_date"] <= train_end]
    validation = df[(df["target_session_date"] > train_end) & (df["target_session_date"] <= val_end)]
    test = df[df["target_session_date"] > val_end]
    return train, validation, test


def _build_pipeline(algorithm: str) -> Pipeline:
    if algorithm == "ridge":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=1.0)),
        ])
    if algorithm == "random_forest":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("model", RandomForestRegressor(
                n_estimators=200, max_depth=6, min_samples_leaf=20, random_state=42, n_jobs=-1
            )),
        ])
    raise ValueError(f"Unknown algorithm: {algorithm}")


def _predict(pipeline: Pipeline, df: pd.DataFrame) -> pd.Series:
    return pd.Series(pipeline.predict(df[FEATURE_COLUMNS]), index=df.index)


def train_baseline_models(
    db: Session, start_date: date, end_date: date, universe_tickers: set[str]
) -> dict:
    """spec §9: linear/regularized regression baseline, then Random Forest —
    not gradient boosting yet ("if it earns its complexity", not by default).
    Both are trained and compared; whichever ranks better on the validation
    set (spec §9: "the product's main output is a ranking") is promoted to
    champion, the other retired — the very first models ever trained have no
    incumbent to beat (spec §12), so this comparison is between each other.
    """
    dataset = load_dataset(db, start_date, end_date, universe_tickers)
    if dataset.empty:
        raise ValueError("No labeled rows available in this date range — run build_historical_dataset first")

    train_df, val_df, test_df = chronological_split(dataset)
    logger.info(
        "Split: %d train rows / %d val rows / %d test rows (%d unique days total)",
        len(train_df), len(val_df), len(test_df), dataset["target_session_date"].nunique(),
    )

    sample_weight = compute_sample_weights(train_df["target_session_date"])

    ARTIFACT_DIR.mkdir(exist_ok=True)
    trained = {}
    for algorithm in ("ridge", "random_forest"):
        pipeline = _build_pipeline(algorithm)
        pipeline.fit(train_df[FEATURE_COLUMNS], train_df[LABEL_COLUMN], model__sample_weight=sample_weight)

        val_predictions = val_df.copy()
        val_predictions["predicted"] = _predict(pipeline, val_df)
        val_metrics = evaluate_predictions(val_predictions, LABEL_COLUMN, "predicted")

        trained[algorithm] = {"pipeline": pipeline, "val_metrics": val_metrics}
        logger.info("%s validation metrics: %s", algorithm, val_metrics)

    ranking_key = lambda algo: trained[algo]["val_metrics"]["mean_rank_ic"] or -999
    champion_algo = max(trained, key=ranking_key)
    retired_algo = next(a for a in trained if a != champion_algo)

    results = {}
    for algorithm, status in ((champion_algo, "champion"), (retired_algo, "retired")):
        pipeline = trained[algorithm]["pipeline"]

        test_predictions = test_df.copy()
        test_predictions["predicted"] = _predict(pipeline, test_df)
        test_metrics = evaluate_predictions(test_predictions, LABEL_COLUMN, "predicted")
        portfolio = (
            simulate_top5_portfolio(test_predictions, "predicted") if status == "champion" else None
        )

        version_label = f"{algorithm}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        artifact_path = ARTIFACT_DIR / f"{version_label}.joblib"
        joblib.dump(pipeline, artifact_path)

        training_run = TrainingRun(
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            train_window_start=train_df["target_session_date"].min(),
            train_window_end=train_df["target_session_date"].max(),
            validation_window_start=val_df["target_session_date"].min(),
            validation_window_end=val_df["target_session_date"].max(),
            test_window_start=test_df["target_session_date"].min(),
            test_window_end=test_df["target_session_date"].max(),
            status="completed",
            notes=f"Baseline bake-off: {algorithm} vs. {retired_algo if status == 'champion' else champion_algo}",
        )
        db.add(training_run)
        db.flush()

        model_version = ModelVersion(
            version_label=version_label,
            algorithm=algorithm,
            feature_set=FEATURE_SET_LABEL,
            trained_at=datetime.now(timezone.utc),
            status=status,
            promoted_at=datetime.now(timezone.utc) if status == "champion" else None,
            hyperparameters={
                "recency_weight_halflife_days": RECENCY_HALFLIFE_DAYS,
                **({"alpha": 1.0} if algorithm == "ridge" else {"n_estimators": 200, "max_depth": 6, "min_samples_leaf": 20}),
            },
            metrics={
                "validation": trained[algorithm]["val_metrics"],
                "test": test_metrics,
                **({"hypothetical_portfolio_test": portfolio} if portfolio else {}),
            },
        )
        db.add(model_version)
        db.flush()

        training_run.resulting_model_version_id = model_version.id
        results[algorithm] = {
            "status": status,
            "version_label": version_label,
            "model_version_id": model_version.id,
            "test_metrics": test_metrics,
        }

    db.commit()
    return results
