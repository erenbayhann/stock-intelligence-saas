from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.ml.evaluate import evaluate_predictions, simulate_top5_portfolio
from app.ml.train import RECENCY_HALFLIFE_DAYS, chronological_split, compute_sample_weights


def test_chronological_split_never_splits_within_a_date():
    dates = [date(2026, 1, d) for d in range(1, 11) for _ in range(3)]  # 3 rows/day, 10 days
    df = pd.DataFrame({"target_session_date": dates, "x": range(30)})

    train, val, test = chronological_split(df, train_fraction=0.7, validation_fraction=0.2)

    train_dates = set(train["target_session_date"])
    val_dates = set(val["target_session_date"])
    test_dates = set(test["target_session_date"])

    # no date appears in more than one split
    assert not (train_dates & val_dates)
    assert not (val_dates & test_dates)
    assert not (train_dates & test_dates)
    # every date's rows land together (3 rows each)
    for d in train_dates:
        assert len(train[train["target_session_date"] == d]) == 3
    # chronological: every train date precedes every val/test date
    assert max(train_dates) < min(val_dates)
    assert max(val_dates) < min(test_dates)


def test_compute_sample_weights_decays_from_most_recent_date():
    dates = pd.Series([
        date(2026, 1, 1),
        date(2026, 1, 1) + pd.Timedelta(days=RECENCY_HALFLIFE_DAYS),
        date(2026, 1, 1) + pd.Timedelta(days=2 * RECENCY_HALFLIFE_DAYS),
    ])

    weights = compute_sample_weights(dates)

    assert weights[2] == pytest.approx(1.0)  # most recent date -> zero age -> weight 1
    # Real half-life: exactly 0.5 at one halflife back, 0.25 at two — not
    # exp(-1)=0.368 / exp(-2)=0.135, which is what the bug used to produce.
    assert weights[1] == pytest.approx(0.5, rel=1e-9)
    assert weights[0] == pytest.approx(0.25, rel=1e-9)


def test_evaluate_predictions_perfect_ranking():
    df = pd.DataFrame({
        "target_session_date": [date(2026, 1, 1)] * 4,
        "actual_excess_return": [0.03, 0.02, -0.01, -0.02],
        "actual_return": [0.05, 0.04, 0.01, -0.01],
        "predicted": [0.03, 0.02, -0.01, -0.02],  # predictions == actuals: perfect rank
    })

    metrics = evaluate_predictions(df, "actual_excess_return", "predicted")

    assert metrics["mae"] == pytest.approx(0.0)
    assert metrics["mean_rank_ic"] == pytest.approx(1.0)
    assert metrics["directional_accuracy"] == pytest.approx(1.0)


def test_evaluate_predictions_precision_at_5_counts_positive_hits_only():
    day = date(2026, 1, 1)
    df = pd.DataFrame({
        "target_session_date": [day] * 5,
        "actual_excess_return": [0.01, 0.02, -0.01, -0.02, 0.03],
        "actual_return": [0.01, 0.02, -0.01, -0.02, 0.03],
        "predicted": [0.05, 0.04, 0.03, 0.02, 0.01],  # top-5 = everyone (only 5 rows)
    })

    metrics = evaluate_predictions(df, "actual_excess_return", "predicted")

    # 3 of 5 actual_excess_return values are positive
    assert metrics["precision_at_5"] == pytest.approx(3 / 5)


def test_simulate_top5_portfolio_applies_transaction_cost():
    day = date(2026, 1, 1)
    df = pd.DataFrame({
        "target_session_date": [day] * 3,
        "actual_return": [0.02, 0.02, 0.02],
        "predicted": [0.03, 0.02, 0.01],
    })

    result = simulate_top5_portfolio(df, "predicted", transaction_cost_bps=10.0)

    assert result["mean_daily_return_net"] == pytest.approx(0.02 - 0.0010)
    assert result["trading_days"] == 1


def test_simulate_top5_portfolio_empty_input_returns_empty_dict():
    df = pd.DataFrame({"target_session_date": [], "actual_return": [], "predicted": []})

    assert simulate_top5_portfolio(df, "predicted") == {}
