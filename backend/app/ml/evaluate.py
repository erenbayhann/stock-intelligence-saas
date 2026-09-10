import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error

TOP_K = 5
POSITIVE_SENTINEL = 0.0


def evaluate_predictions(df: pd.DataFrame, actual_col: str, predicted_col: str) -> dict:
    """Regression + ranking-quality metrics (spec §14), computed per
    target_session_date then averaged across days for the ranking metrics —
    a single pooled Spearman correlation across all days/tickers would
    conflate cross-sectional ranking skill with time-series trend, which
    isn't what "ranking quality" means for a daily top-5 product.
    """
    mae = mean_absolute_error(df[actual_col], df[predicted_col])
    rmse = mean_squared_error(df[actual_col], df[predicted_col]) ** 0.5
    directional_accuracy = float(
        (np.sign(df[actual_col]) == np.sign(df[predicted_col])).mean()
    )

    daily_rank_ic = []
    daily_precision_at_k = []
    daily_mean_actual_return = []
    daily_mean_excess_return = []

    for _, day_df in df.groupby("target_session_date"):
        if len(day_df) >= 2:
            corr, _ = spearmanr(day_df[predicted_col], day_df[actual_col])
            if not np.isnan(corr):
                daily_rank_ic.append(corr)

        top_k = day_df.nlargest(min(TOP_K, len(day_df)), predicted_col)
        daily_precision_at_k.append(float((top_k[actual_col] > POSITIVE_SENTINEL).mean()))
        daily_mean_actual_return.append(float(top_k["actual_return"].mean()))
        daily_mean_excess_return.append(float(top_k[actual_col].mean()))

    return {
        "mae": float(mae),
        "rmse": float(rmse),
        "directional_accuracy": directional_accuracy,
        "mean_rank_ic": float(np.mean(daily_rank_ic)) if daily_rank_ic else None,
        "precision_at_5": float(np.mean(daily_precision_at_k)) if daily_precision_at_k else None,
        "mean_actual_return_top5": float(np.mean(daily_mean_actual_return)) if daily_mean_actual_return else None,
        "mean_excess_return_top5": float(np.mean(daily_mean_excess_return)) if daily_mean_excess_return else None,
        "n_rows": int(len(df)),
        "n_days": int(df["target_session_date"].nunique()),
    }


def simulate_top5_portfolio(df: pd.DataFrame, predicted_col: str, transaction_cost_bps: float = 10.0) -> dict:
    """A hypothetical equal-weight, daily-rebalanced top-5 strategy (spec
    §14/§21) — explicitly hypothetical, net of an assumed round-trip
    transaction cost since the whole book turns over every session. Never
    presented as an actual/live trading result (spec §23).
    """
    cost = transaction_cost_bps / 10_000
    daily_returns = []
    for day, day_df in df.groupby("target_session_date"):
        top_k = day_df.nlargest(min(TOP_K, len(day_df)), predicted_col)
        gross_return = float(top_k["actual_return"].mean())
        daily_returns.append(gross_return - cost)

    if not daily_returns:
        return {}

    returns = pd.Series(daily_returns)
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    sharpe_like = (
        float(returns.mean() / returns.std() * (252 ** 0.5)) if returns.std() > 0 else None
    )

    return {
        "transaction_cost_bps": transaction_cost_bps,
        "mean_daily_return_net": float(returns.mean()),
        "cumulative_return_net": float(cumulative.iloc[-1] - 1),
        "max_drawdown": float(drawdown.min()),
        "sharpe_like_annualized": sharpe_like,
        "trading_days": int(len(returns)),
    }
