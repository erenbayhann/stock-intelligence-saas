import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.security import Security
from app.services.feature_service import (
    compute_benchmark_features,
    compute_macro_features,
    compute_sector_peer_returns_20d,
    generate_feature_snapshot,
    historical_as_of_cutoffs,
)
from app.services.label_service import compute_realized_label, get_trading_days

logger = logging.getLogger(__name__)


def build_historical_dataset(
    db: Session, start_date: date, end_date: date, universe_tickers: set[str]
) -> dict:
    """The Phase 4 deliverable (spec §26 item 4): for every real trading day
    in [start_date, end_date] and every universe security, builds a
    point-in-time-correct historical feature snapshot (persisted to
    feature_snapshots, same table live use writes to) and its realized label
    (spec §2), returning the assembled (features, label) rows in-memory for
    Phase 5 to consume directly — no separate training-examples table exists
    in the schema, and re-deriving this from feature_snapshots + market_prices
    on demand avoids a second copy of data that could drift out of sync.

    Market/fundamental/macro/news data completeness degrades further back in
    history by construction, not by bug: news was never backfilled (spec §5/
    data-ingestion-plan_1.md §5, avoids train-serve skew), macro only goes back
    ~2 years (see app/providers/macro/fred.py's vintage caveat), and
    fundamentals only as far as each company's pulled XBRL history. Rows
    reflect that honestly with NULLs rather than fabricating coverage.
    """
    trading_days = get_trading_days(db, start_date, end_date)
    securities = db.execute(
        select(Security.id, Security.ticker, Company.sector)
        .join(Company, Security.company_id == Company.id)
        .where(Security.is_active.is_(True), Security.ticker.in_(universe_tickers))
    ).all()

    snapshots_written = 0
    labeled_rows = 0
    dataset: list[dict] = []

    for target_day in trading_days:
        market_cutoff, intraday_cutoff = historical_as_of_cutoffs(target_day)

        benchmark_features, benchmark_return_20d = compute_benchmark_features(db, market_cutoff)
        sector_peer_returns_20d = compute_sector_peer_returns_20d(db, market_cutoff, universe_tickers)
        macro_features = compute_macro_features(db, intraday_cutoff)

        for security_id, ticker, sector in securities:
            snapshot = generate_feature_snapshot(
                db,
                security_id,
                sector,
                market_as_of=market_cutoff,
                intraday_as_of=intraday_cutoff,
                benchmark_features=benchmark_features,
                benchmark_return_20d=benchmark_return_20d,
                sector_peer_returns_20d=sector_peer_returns_20d,
                macro_features=macro_features,
                snapshot_as_of=intraday_cutoff,
            )
            snapshots_written += 1

            label = compute_realized_label(db, security_id, target_day)
            if label is not None:
                dataset.append(
                    {
                        "security_id": security_id,
                        "ticker": ticker,
                        "target_session_date": target_day.isoformat(),
                        "features": snapshot.features,
                        **label,
                    }
                )
                labeled_rows += 1

        db.commit()  # one transaction per day keeps commits reasonably sized
        logger.info("Built %s: %d securities", target_day, len(securities))

    return {
        "trading_days": len(trading_days),
        "snapshots_written": snapshots_written,
        "labeled_rows": labeled_rows,
        "dataset": dataset,
    }
