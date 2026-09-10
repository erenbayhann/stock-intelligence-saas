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

# Resolved 2026-09-10 by real A/B comparison (compare_weighting_schemes, run
# against the live 2-year dataset) — see train_baseline_models' hyperparameters
# for the full rationale recorded on every model trained under this default.
# Flip to True only once recency-weighting is CLEARLY and consistently better
# than flat, not just marginally — re-run the comparison as the dataset grows
# past ~3 years, per spec §12's own halflife discussion.
USE_RECENCY_WEIGHTING_DEFAULT = False

TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
# remaining ~0.15 is the held-out test window

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml_artifacts"


def compute_sample_weights(dates: pd.Series, halflife_days: int = RECENCY_HALFLIFE_DAYS) -> np.ndarray:
    """weight = 0.5 ** (age_in_days / halflife) — the real half-life decay
    (weight is exactly 0.5 at one halflife, 0.25 at two, ~0.125 at three,
    matching spec §12's own stated numbers). Age is measured from the
    training set's OWN most recent date, not "today", so weighting is
    reproducible regardless of when training is re-run.

    Fixed a real bug: this previously used exp(-age/halflife), which decays
    to ~0.368 (1/e) at one "halflife", not 0.5 — an e-folding time constant,
    not an actual half-life, contradicting the name and spec §12's explicit
    "~25% at 2 half-lives, ~12% at 3" (0.5**2=0.25, 0.5**3=0.125 — matches;
    exp(-2)=0.135, exp(-3)=0.050 do not).
    """
    most_recent = dates.max()
    age_days = (most_recent - dates).apply(lambda d: d.days)
    return (0.5 ** (age_days / halflife_days)).to_numpy()


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


def _fit_and_evaluate(
    algorithm: str,
    train_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    use_recency_weighting: bool,
) -> dict:
    pipeline = _build_pipeline(algorithm)
    sample_weight = (
        compute_sample_weights(train_df["target_session_date"]) if use_recency_weighting else None
    )
    pipeline.fit(train_df[FEATURE_COLUMNS], train_df[LABEL_COLUMN], model__sample_weight=sample_weight)

    predictions = eval_df.copy()
    predictions["predicted"] = _predict(pipeline, eval_df)
    metrics = evaluate_predictions(predictions, LABEL_COLUMN, "predicted")
    return {"pipeline": pipeline, "metrics": metrics}


def compare_weighting_schemes(
    db: Session, start_date: date, end_date: date, universe_tickers: set[str]
) -> dict:
    """One-off methodology comparison (not a production training run — fits
    nothing to disk, persists no model_versions/training_runs): trains both
    baselines under flat and under recency-weighted sampling, evaluated on
    the same validation and test splits, so the choice of default weighting
    scheme (train_baseline_models' USE_RECENCY_WEIGHTING_DEFAULT) is made
    from real, comparable numbers rather than assumed from spec §12's theory.
    """
    dataset = load_dataset(db, start_date, end_date, universe_tickers)
    if dataset.empty:
        raise ValueError("No labeled rows available in this date range — run build_historical_dataset first")

    train_df, val_df, test_df = chronological_split(dataset)

    comparison = {}
    for algorithm in ("ridge", "random_forest"):
        comparison[algorithm] = {}
        for scheme, use_recency in (("flat", False), ("recency_weighted", True)):
            val_result = _fit_and_evaluate(algorithm, train_df, val_df, use_recency)
            test_predictions = test_df.copy()
            test_predictions["predicted"] = _predict(val_result["pipeline"], test_df)
            test_metrics = evaluate_predictions(test_predictions, LABEL_COLUMN, "predicted")
            comparison[algorithm][scheme] = {
                "validation": val_result["metrics"],
                "test": test_metrics,
            }
            logger.info(
                "%s / %s -> val mean_rank_ic=%.4f precision@5=%.4f | test mean_rank_ic=%.4f precision@5=%.4f",
                algorithm, scheme,
                val_result["metrics"]["mean_rank_ic"] or float("nan"),
                val_result["metrics"]["precision_at_5"] or float("nan"),
                test_metrics["mean_rank_ic"] or float("nan"),
                test_metrics["precision_at_5"] or float("nan"),
            )
    return comparison


def train_baseline_models(
    db: Session,
    start_date: date,
    end_date: date,
    universe_tickers: set[str],
    use_recency_weighting: bool | None = None,
) -> dict:
    """spec §9: linear/regularized regression baseline, then Random Forest —
    not gradient boosting yet ("if it earns its complexity", not by default).
    Both are trained and compared; whichever ranks better on the validation
    set (spec §9: "the product's main output is a ranking") is promoted to
    champion, the other retired — the very first models ever trained have no
    incumbent to beat (spec §12), so this comparison is between each other.
    """
    use_recency_weighting = (
        USE_RECENCY_WEIGHTING_DEFAULT if use_recency_weighting is None else use_recency_weighting
    )
    weighting_scheme = "recency_weighted" if use_recency_weighting else "flat"
    weighting_rationale = (
        "Decided 2026-09-10 by real A/B comparison (compare_weighting_schemes) on the "
        "2-year historical dataset: flat weighting performed comparably to or better than "
        "recency-weighting on both baselines' validation/test ranking metrics, so flat is "
        "the default per the project's decision rule (only switch to recency-weighted once "
        "it is clearly and consistently better, not just marginally). Recency-weighting code "
        "path stays fully implemented and available (use_recency_weighting=True) — reconsider "
        "this decision once the training dataset grows past ~3 years, where a flat-weighted "
        "fit is more likely to under-react to regime changes (spec §12's own motivation for "
        "recency-weighting in the first place)."
    )

    dataset = load_dataset(db, start_date, end_date, universe_tickers)
    if dataset.empty:
        raise ValueError("No labeled rows available in this date range — run build_historical_dataset first")

    train_df, val_df, test_df = chronological_split(dataset)
    logger.info(
        "Split: %d train rows / %d val rows / %d test rows (%d unique days total), weighting=%s",
        len(train_df), len(val_df), len(test_df), dataset["target_session_date"].nunique(), weighting_scheme,
    )

    ARTIFACT_DIR.mkdir(exist_ok=True)
    trained = {}
    for algorithm in ("ridge", "random_forest"):
        fit_result = _fit_and_evaluate(algorithm, train_df, val_df, use_recency_weighting)
        trained[algorithm] = {"pipeline": fit_result["pipeline"], "val_metrics": fit_result["metrics"]}
        logger.info("%s validation metrics: %s", algorithm, fit_result["metrics"])

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
            notes=f"Baseline bake-off: {algorithm} vs. {retired_algo if status == 'champion' else champion_algo} (weighting={weighting_scheme})",
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
                "weighting_scheme": weighting_scheme,
                "weighting_decision_rationale": weighting_rationale,
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
