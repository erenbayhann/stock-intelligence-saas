import logging
from datetime import date, datetime, timezone

import joblib
import lightgbm as lgb
import pandas as pd
import xgboost as xgb
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sqlalchemy.orm import Session

from app.ml.dataset import FEATURE_COLUMNS, FEATURE_SET_LABEL, LABEL_COLUMN, load_dataset
from app.ml.evaluate import evaluate_predictions, simulate_top5_portfolio
from app.ml.train import ARTIFACT_DIR, USE_RECENCY_WEIGHTING_DEFAULT, chronological_split, compute_sample_weights
from app.models.model_version import ModelVersion
from app.models.training_run import TrainingRun

logger = logging.getLogger(__name__)

# spec §9: "gradient boosting (XGBoost or LightGBM) if it earns its
# complexity" — these are measurement-only challengers, never
# auto-promoted (persisted as status='challenger', the admin decides,
# spec §12/§15).
GBM_HYPERPARAMS = dict(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8)

REGRESSION_ALGORITHMS = ("xgboost", "lightgbm")
RANKING_ALGORITHMS = ("xgboost_ranking", "lightgbm_ranking")
ALL_CHALLENGER_ALGORITHMS = REGRESSION_ALGORITHMS + RANKING_ALGORITHMS


def _build_regression_pipeline(algorithm: str) -> Pipeline:
    if algorithm == "xgboost":
        model = xgb.XGBRegressor(objective="reg:squarederror", random_state=42, n_jobs=-1, **GBM_HYPERPARAMS)
    elif algorithm == "lightgbm":
        model = lgb.LGBMRegressor(objective="regression", random_state=42, n_jobs=-1, verbosity=-1, **GBM_HYPERPARAMS)
    else:
        raise ValueError(f"Unknown regression algorithm: {algorithm}")
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", model)])


def _build_ranking_pipeline(algorithm: str) -> Pipeline:
    if algorithm == "xgboost_ranking":
        # rank:ndcg requires the label to be a non-negative INTEGER relevance
        # grade (a real constraint hit while testing this: XGBoost raises
        # "label must be either 0 or positive integer" against our
        # continuous, signed actual_excess_return) — rank:pairwise has no
        # such requirement, since it only compares the RELATIVE order of
        # continuous scores within each day's group, which is exactly what
        # this product's ranking objective actually needs.
        model = xgb.XGBRanker(objective="rank:pairwise", random_state=42, n_jobs=-1, **GBM_HYPERPARAMS)
    elif algorithm == "lightgbm_ranking":
        model = lgb.LGBMRanker(objective="lambdarank", random_state=42, n_jobs=-1, verbosity=-1, **GBM_HYPERPARAMS)
    else:
        raise ValueError(f"Unknown ranking algorithm: {algorithm}")
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("model", model)])


def _group_sizes(df: pd.DataFrame) -> list[int]:
    """Learning-to-rank objectives need contiguous per-day query groups.
    load_dataset() builds rows day-by-day already, and chronological_split
    only ever takes contiguous date-bounded slices, so train/val/test rows
    stay grouped by target_session_date in original row order — this just
    reads off the sizes, it doesn't need to re-sort anything.
    """
    return df.groupby("target_session_date", sort=False).size().tolist()


LIGHTGBM_RELEVANCE_BINS = 5


def _lightgbm_relevance_labels(df: pd.DataFrame) -> pd.Series:
    """LightGBM's lambdarank (unlike XGBoost's rank:pairwise) requires
    non-negative integer relevance grades, not a continuous score — hit as
    "label should be int type ... for ranking task" against our continuous,
    signed actual_excess_return. A plain per-day ordinal rank would satisfy
    "integer", but our universe has ~100 tickers/day, and LightGBM's default
    label_gain table only covers relevance levels 0-30 — ranks that high
    raise a label_gain/relevance-level mismatch. Quantile-bucketing each
    day's labels into a handful of grades keeps the same within-day ordering
    information a ranking loss needs while staying well inside that range.
    """

    def _bucket(day_labels: pd.Series) -> pd.Series:
        try:
            return pd.qcut(day_labels, LIGHTGBM_RELEVANCE_BINS, labels=False, duplicates="drop")
        except ValueError:
            return pd.Series(0, index=day_labels.index)

    return (
        df.groupby("target_session_date")[LABEL_COLUMN]
        .transform(_bucket)
        .fillna(0)
        .astype(int)
    )


def _predict(pipeline: Pipeline, df: pd.DataFrame) -> pd.Series:
    return pd.Series(pipeline.predict(df[FEATURE_COLUMNS]), index=df.index)


def _fit_challenger(algorithm: str, train_df: pd.DataFrame, use_recency_weighting: bool) -> Pipeline:
    sample_weight = compute_sample_weights(train_df["target_session_date"]) if use_recency_weighting else None

    if algorithm in REGRESSION_ALGORITHMS:
        pipeline = _build_regression_pipeline(algorithm)
        pipeline.fit(train_df[FEATURE_COLUMNS], train_df[LABEL_COLUMN], model__sample_weight=sample_weight)
        return pipeline

    if algorithm in RANKING_ALGORITHMS:
        pipeline = _build_ranking_pipeline(algorithm)
        # Ranking objectives use the group structure, not per-row sample
        # weights — recency-weighting doesn't have a clean equivalent here
        # (a per-query, not per-row, weight would be needed), so it's
        # deliberately not applied to the ranking-mode challengers.
        # xgboost_ranking (rank:pairwise) trains directly on the continuous
        # excess-return label; lightgbm_ranking (lambdarank) needs the
        # bucketed integer relevance grades — see _lightgbm_relevance_labels.
        label = (
            _lightgbm_relevance_labels(train_df) if algorithm == "lightgbm_ranking" else train_df[LABEL_COLUMN]
        )
        pipeline.fit(train_df[FEATURE_COLUMNS], label, model__group=_group_sizes(train_df))
        return pipeline

    raise ValueError(f"Unknown challenger algorithm: {algorithm}")


def train_challengers(
    db: Session,
    start_date: date,
    end_date: date,
    universe_tickers: set[str],
    algorithms: tuple[str, ...] = ALL_CHALLENGER_ALGORITHMS,
    use_recency_weighting: bool | None = None,
) -> dict:
    """Measurement-only run (spec §9's "if it earns its complexity" question,
    spec §12's challenger mechanic): trains each requested gradient-boosting
    variant, evaluates it exactly like the baselines, and persists it with
    status='challenger' — NEVER touches the current champion or auto-
    promotes anything. Ranking-mode note: rank:pairwise/lambdarank optimize
    ordering, not the regression target itself, so their MAE/RMSE/
    directional_accuracy numbers are not directly comparable to the
    regression models' — mean_rank_ic and precision_at_5 are the fair
    comparison metrics for those two.
    """
    use_recency_weighting = (
        USE_RECENCY_WEIGHTING_DEFAULT if use_recency_weighting is None else use_recency_weighting
    )

    dataset = load_dataset(db, start_date, end_date, universe_tickers)
    if dataset.empty:
        raise ValueError("No labeled rows available in this date range — run build_historical_dataset first")

    train_df, val_df, test_df = chronological_split(dataset)
    ARTIFACT_DIR.mkdir(exist_ok=True)

    results = {}
    for algorithm in algorithms:
        pipeline = _fit_challenger(algorithm, train_df, use_recency_weighting)

        val_predictions = val_df.copy()
        val_predictions["predicted"] = _predict(pipeline, val_df)
        val_metrics = evaluate_predictions(val_predictions, LABEL_COLUMN, "predicted")

        test_predictions = test_df.copy()
        test_predictions["predicted"] = _predict(pipeline, test_df)
        test_metrics = evaluate_predictions(test_predictions, LABEL_COLUMN, "predicted")
        portfolio = simulate_top5_portfolio(test_predictions, "predicted")

        version_label = f"{algorithm}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        joblib.dump(pipeline, ARTIFACT_DIR / f"{version_label}.joblib")

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
            notes=f"Measurement-only challenger run ({algorithm}) vs. current champion — spec §9",
        )
        db.add(training_run)
        db.flush()

        model_version = ModelVersion(
            version_label=version_label,
            algorithm=algorithm,
            feature_set=FEATURE_SET_LABEL,
            trained_at=datetime.now(timezone.utc),
            status="challenger",
            promoted_at=None,
            hyperparameters={
                "weighting_scheme": "recency_weighted" if (use_recency_weighting and algorithm in REGRESSION_ALGORITHMS) else "flat",
                **GBM_HYPERPARAMS,
                **({"objective": "rank:pairwise" if algorithm == "xgboost_ranking" else "lambdarank"} if algorithm in RANKING_ALGORITHMS else {}),
                **({"label_encoding": "per_day_quantile_relevance_grade", "relevance_bins": LIGHTGBM_RELEVANCE_BINS} if algorithm == "lightgbm_ranking" else {}),
            },
            metrics={
                "validation": val_metrics,
                "test": test_metrics,
                "hypothetical_portfolio_test": portfolio or None,
            },
        )
        db.add(model_version)
        db.flush()
        training_run.resulting_model_version_id = model_version.id

        results[algorithm] = {
            "model_version_id": model_version.id,
            "version_label": version_label,
            "validation": val_metrics,
            "test": test_metrics,
        }
        logger.info("%s -> val mean_rank_ic=%.4f, test mean_rank_ic=%.4f", algorithm, val_metrics["mean_rank_ic"] or float("nan"), test_metrics["mean_rank_ic"] or float("nan"))

    db.commit()
    return results
