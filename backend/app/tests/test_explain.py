import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from app.ml.dataset import FEATURE_COLUMNS
from app.ml.explain import explain_prediction, get_global_feature_importances


def _fit_rf_pipeline(n=60):
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(n, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    y = X["return_20d"] * 2 + rng.normal(scale=0.1, size=n)  # return_20d dominates by construction
    pipeline = Pipeline([("impute", SimpleImputer(strategy="median")), ("model", RandomForestRegressor(n_estimators=20, random_state=0))])
    pipeline.fit(X, y)
    return pipeline, X


def test_get_global_feature_importances_ranks_the_dominant_feature_first():
    pipeline, _ = _fit_rf_pipeline()

    importances = get_global_feature_importances(pipeline)

    assert importances.index[0] == "return_20d"


def test_get_global_feature_importances_handles_imputer_dropped_columns():
    # Regression test: a real crash hit running the live prediction job.
    # ev_ebitda/net_debt_ebitda are always 100% missing by design, and
    # SimpleImputer silently drops fully-missing columns (keep_empty_features
    # defaults to False), so feature_importances_ ends up SHORTER than
    # FEATURE_COLUMNS — indexing blindly by FEATURE_COLUMNS crashes with a
    # pandas length-mismatch error.
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(60, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    X["ev_ebitda"] = np.nan
    X["net_debt_ebitda"] = np.nan
    y = X["return_20d"] * 2 + rng.normal(scale=0.1, size=60)
    pipeline = Pipeline([("impute", SimpleImputer(strategy="median")), ("model", RandomForestRegressor(n_estimators=20, random_state=0))])
    pipeline.fit(X, y)

    importances = get_global_feature_importances(pipeline)

    assert "ev_ebitda" not in importances.index
    assert "net_debt_ebitda" not in importances.index
    assert len(importances) == len(FEATURE_COLUMNS) - 2
    assert importances.index[0] == "return_20d"


def test_get_global_feature_importances_works_for_linear_coef():
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(60, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    y = X["pe_ratio"] * 3 + rng.normal(scale=0.1, size=60)
    pipeline = Pipeline([("impute", SimpleImputer(strategy="median")), ("model", Ridge())])
    pipeline.fit(X, y)

    importances = get_global_feature_importances(pipeline)

    assert importances.index[0] == "pe_ratio"


def test_explain_prediction_flags_notably_extreme_values():
    pipeline, cohort = _fit_rf_pipeline()
    # This row's return_20d is a clear outlier vs. the cohort (which is ~N(0,1))
    row_features = {col: 0.0 for col in FEATURE_COLUMNS}
    row_features["return_20d"] = 5.0

    explanation = explain_prediction(pipeline, row_features, cohort)

    assert "20-day price momentum" in explanation
    assert "above the group average" in explanation


def test_explain_prediction_ignores_identical_macro_columns_despite_float_noise():
    # Regression test for a real bug found running the live prediction job:
    # a macro feature is the SAME value for every security that day (true
    # variance is exactly zero), but pandas' std() on identical floats
    # returned ~7e-15, not exactly 0.0 — `not std` didn't catch that, so
    # dividing by the near-zero std produced a meaningless huge z-score and
    # flagged VIX as "notable" for every single one of the top 5 picks.
    pipeline, cohort = _fit_rf_pipeline()
    cohort = cohort.copy()
    cohort["macro_vixcls"] = 16.46  # identical for every row, like the real bug

    row_features = {col: 0.0 for col in FEATURE_COLUMNS}
    row_features["macro_vixcls"] = 16.46  # this security's own value, same as everyone else's

    explanation = explain_prediction(pipeline, row_features, cohort)

    assert "VIX" not in explanation


def test_explain_prediction_falls_back_when_nothing_stands_out():
    pipeline, cohort = _fit_rf_pipeline()
    row_features = {col: float(cohort[col].mean()) for col in FEATURE_COLUMNS}  # perfectly average

    explanation = explain_prediction(pipeline, row_features, cohort)

    assert "no single factor stood out" in explanation
