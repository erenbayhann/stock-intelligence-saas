import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from app.ml.dataset import FEATURE_COLUMNS

# Human-readable labels for the explanation (spec §10). Kept short and
# factual — no invented narrative, just what the number is.
FEATURE_LABELS: dict[str, str] = {
    "return_1d": "1-day price return",
    "return_5d": "5-day price return",
    "return_20d": "20-day price momentum",
    "return_60d": "60-day price momentum",
    "volume": "trading volume",
    "volume_change": "day-over-day volume change",
    "relative_volume": "volume vs. its own 20-day average",
    "moving_avg_20d": "20-day moving average",
    "moving_avg_50d": "50-day moving average",
    "realized_volatility_20d": "20-day realized volatility",
    "benchmark_return_1d": "S&P 500 1-day return",
    "benchmark_return_5d": "S&P 500 5-day return",
    "benchmark_return_20d": "S&P 500 20-day return",
    "relative_strength_20d": "20-day performance vs. the S&P 500",
    "sector_relative_performance_20d": "20-day performance vs. sector peers",
    "revenue_growth": "revenue growth",
    "earnings_growth": "earnings growth",
    "eps": "earnings per share",
    "pe_ratio": "P/E ratio",
    "price_to_book": "price-to-book ratio",
    "ev_ebitda": "EV/EBITDA",
    "debt_equity": "debt-to-equity",
    "net_debt_ebitda": "net debt/EBITDA",
    "roe": "return on equity",
    "operating_margin": "operating margin",
    "free_cash_flow": "free cash flow",
    "market_cap": "market capitalization",
    "dividend_yield": "dividend yield",
    "macro_dgs10": "10-year Treasury yield",
    "macro_dgs2": "2-year Treasury yield",
    "macro_fedfunds": "federal funds rate",
    "macro_cpiaucsl": "CPI level",
    "macro_unrate": "unemployment rate",
    "macro_vixcls": "market volatility (VIX)",
}

TOP_N_FACTORS = 5
Z_SCORE_NOTABLE_THRESHOLD = 0.5


def get_global_feature_importances(pipeline: Pipeline) -> pd.Series:
    """Real, model-derived importances (spec §10: "use real feature
    importance / SHAP-style explanations", never an LLM inventing reasons).

    Must be indexed by whichever columns actually reached the model, not
    blindly by FEATURE_COLUMNS: SimpleImputer silently drops any column that
    is 100% missing in the training data (e.g. ev_ebitda, net_debt_ebitda,
    deliberately never computed — see app/providers/fundamentals/sec_edgar.py)
    with `keep_empty_features=False` (the default), so a fitted model's
    feature_importances_/coef_ can be shorter than FEATURE_COLUMNS. Hit this
    as a real crash running the live prediction job, not a hypothetical.
    """
    model = pipeline.named_steps["model"]
    surviving_columns = pipeline.named_steps["impute"].get_feature_names_out(FEATURE_COLUMNS)

    if hasattr(model, "feature_importances_"):
        values = model.feature_importances_
    elif hasattr(model, "coef_"):
        values = np.abs(model.coef_)
    else:
        raise ValueError(f"Model {type(model)} exposes neither feature_importances_ nor coef_")
    return pd.Series(values, index=surviving_columns).sort_values(ascending=False)


def explain_prediction(
    pipeline: Pipeline, row_features: dict, cohort_df: pd.DataFrame
) -> str:
    """Picks the model's most important features overall, then describes
    only the ones where THIS security is notably above/below its peers
    today (cohort_df = every candidate scored in the same run) — a
    factual, data-driven explanation, not a narrative invented after the
    fact (spec §10).
    """
    importances = get_global_feature_importances(pipeline)

    clauses = []
    for feature in importances.index:
        if feature not in cohort_df.columns:
            continue
        value = row_features.get(feature)
        if value is None:
            continue

        cohort_values = cohort_df[feature].dropna()
        if len(cohort_values) < 5:
            continue
        mean, std = cohort_values.mean(), cohort_values.std()
        # A macro feature (same value for every security that day) has
        # ZERO true variance, but pandas' std() on identical floats can
        # return a tiny nonzero value (~1e-15) from floating-point rounding
        # in its variance algorithm, not exactly 0.0 — `not std` alone
        # missed this in practice and produced a meaningless huge z-score
        # from dividing by near-zero. Use an epsilon relative to the
        # feature's own scale instead of an exact zero check.
        if np.isnan(std) or std < 1e-9 * max(abs(mean), 1.0):
            continue

        z = (value - mean) / std
        if abs(z) < Z_SCORE_NOTABLE_THRESHOLD:
            continue

        label = FEATURE_LABELS.get(feature, feature)
        direction = "above" if z > 0 else "below"
        clauses.append(f"{label} notably {direction} the group average")

        if len(clauses) >= TOP_N_FACTORS:
            break

    if not clauses:
        return "Ranked by the model's overall predicted score; no single factor stood out strongly from the group."
    return "Key factors: " + "; ".join(clauses) + "."
