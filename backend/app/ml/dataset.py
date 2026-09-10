from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.feature_snapshot import FeatureSnapshot
from app.models.security import Security
from app.services.feature_service import historical_as_of_cutoffs
from app.services.label_service import compute_realized_label, get_trading_days

# spec §12's "price_fundamentals_macro" lineage — news features are
# deliberately excluded here. Real news coverage is only ~2 days deep so
# far, nowhere near spec §15's 60-trading-day/80%-coverage eligibility bar
# for the news-inclusive lineage; including near-always-null news columns
# now would just be noise, not signal.
FEATURE_COLUMNS: list[str] = [
    "return_1d", "return_5d", "return_20d", "return_60d",
    "volume", "volume_change", "relative_volume",
    "moving_avg_20d", "moving_avg_50d", "realized_volatility_20d",
    "benchmark_return_1d", "benchmark_return_5d", "benchmark_return_20d",
    "relative_strength_20d", "sector_relative_performance_20d",
    "revenue_growth", "earnings_growth", "eps", "pe_ratio", "price_to_book",
    "ev_ebitda", "debt_equity", "net_debt_ebitda", "roe", "operating_margin",
    "free_cash_flow", "market_cap", "dividend_yield",
    "macro_dgs10", "macro_dgs2", "macro_fedfunds", "macro_cpiaucsl",
    "macro_unrate", "macro_vixcls",
]
FEATURE_SET_LABEL = "price_fundamentals_macro"
LABEL_COLUMN = "actual_excess_return"


def load_dataset(db: Session, start_date: date, end_date: date, universe_tickers: set[str]) -> pd.DataFrame:
    """Reads Phase 4's already-persisted, point-in-time-correct
    feature_snapshots and joins each to its realized label (spec §2) —
    never re-derives features from providers. Looks each snapshot up by its
    exact deterministic as_of (historical_as_of_cutoffs' intraday_cutoff),
    which is how Phase 4 wrote them, so this can never accidentally pick up
    an unrelated live snapshot (whose as_of is `datetime.now()`, not this
    fixed per-day value).
    """
    securities = db.execute(
        select(Security.id, Security.ticker)
        .join(Company, Security.company_id == Company.id)
        .where(Security.is_active.is_(True), Security.ticker.in_(universe_tickers))
    ).all()
    ticker_by_id = {s.id: s.ticker for s in securities}
    security_ids = list(ticker_by_id.keys())

    trading_days = get_trading_days(db, start_date, end_date)
    rows: list[dict] = []

    for target_day in trading_days:
        _, intraday_cutoff = historical_as_of_cutoffs(target_day)
        snapshots = db.scalars(
            select(FeatureSnapshot).where(
                FeatureSnapshot.as_of == intraday_cutoff,
                FeatureSnapshot.security_id.in_(security_ids),
            )
        ).all()

        for snap in snapshots:
            label = compute_realized_label(db, snap.security_id, target_day)
            if label is None:
                continue
            row = {col: snap.features.get(col) for col in FEATURE_COLUMNS}
            row.update(label)
            row["security_id"] = snap.security_id
            row["ticker"] = ticker_by_id[snap.security_id]
            row["target_session_date"] = target_day
            rows.append(row)

    return pd.DataFrame(rows)
