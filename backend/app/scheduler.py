"""Entrypoint: python -m app.scheduler

Phase 10 (spec §26 item 10 / §20): the single scheduler process that fires
every background job on the cadence in docs/data-ingestion-plan_1.md §3,
amended for what Phase 1-7 actually built (see that doc's "Phase 10
amendments" note — no extended-hours bars, SEC EDGAR full-universe pulls
instead of an FMP weekly rotation). Runs as its own docker-compose service
sharing the backend image; the API process never schedules anything itself.

Each job's own CLI module (app/jobs/*.py) already owns its DB session,
settings, and job_runs bookkeeping (track_job_run) — this module only calls
those main() functions on a timer. A job that raises is caught, logged, and
recorded (track_job_run already writes the failed job_runs row before
re-raising) without taking down the scheduler process or any other job's
future runs; APScheduler's executor isolates jobs from each other by
design, and the try/except below makes that explicit rather than relying on
it silently.
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs import (
    backfill_market_data,
    build_historical_dataset,
    check_champion_performance,
    evaluate_results,
    generate_features,
    generate_predictions,
    ingest_filings,
    ingest_fundamentals,
    ingest_macro,
    ingest_news,
    train_challengers,
    train_model,
)

logger = logging.getLogger(__name__)

ET = "America/New_York"


def _run(job_label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        # track_job_run already persisted the failure and logged the
        # traceback — this just guarantees it can never propagate into
        # APScheduler and take out this or any other job's future runs.
        logger.error("Scheduled job %s raised — see job_runs for detail", job_label)


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=ET)

    # -- Nightly market close --------------------------------------------
    scheduler.add_job(
        _run, CronTrigger(hour=16, minute=20, timezone=ET),
        args=["market_data_ingestion", backfill_market_data.main], kwargs={"days_back": 5},
        id="market_data_ingestion", misfire_grace_time=600,
    )
    scheduler.add_job(
        _run, CronTrigger(hour=16, minute=25, timezone=ET),
        args=["result_evaluation", evaluate_results.main],
        id="result_evaluation", misfire_grace_time=600,
    )
    scheduler.add_job(
        _run, CronTrigger(hour=16, minute=30, timezone=ET),
        args=["champion_performance_check", check_champion_performance.main],
        id="champion_performance_check", misfire_grace_time=600,
    )

    # -- News: 7 sweeps across the closed window + pre-market (§2/§3) ----
    for hour, minute in [(17, 0), (19, 30), (22, 0), (0, 30), (3, 0), (6, 0), (8, 45)]:
        scheduler.add_job(
            _run, CronTrigger(hour=hour, minute=minute, timezone=ET),
            args=[f"news_ingestion_{hour:02d}{minute:02d}", ingest_news.main],
            id=f"news_ingestion_{hour:02d}{minute:02d}", misfire_grace_time=900,
        )

    # -- Macro / fundamentals / filings -----------------------------------
    scheduler.add_job(
        _run, CronTrigger(hour=20, minute=30, timezone=ET),
        args=["macro_ingestion", ingest_macro.main],
        id="macro_ingestion", misfire_grace_time=1800,
    )
    scheduler.add_job(
        _run, CronTrigger(hour=21, minute=0, timezone=ET),
        args=["fundamentals_ingestion", ingest_fundamentals.main],
        id="fundamentals_ingestion", misfire_grace_time=1800,
    )
    scheduler.add_job(
        _run, IntervalTrigger(minutes=30),
        args=["filings_ingestion", ingest_filings.main],
        id="filings_ingestion", misfire_grace_time=600,
    )

    # -- Feature freeze -> inference -> prediction lock (before 09:30 open) --
    scheduler.add_job(
        _run, CronTrigger(hour=9, minute=5, timezone=ET),
        args=["feature_generation", generate_features.main],
        id="feature_generation", misfire_grace_time=300,
    )
    scheduler.add_job(
        _run, CronTrigger(hour=9, minute=15, timezone=ET),
        args=["prediction_generation", generate_predictions.main],
        id="prediction_generation", misfire_grace_time=300,
    )

    # -- Weekly retrain, Sunday when markets are closed and nothing else --
    # -- is contending for API/DB time (spec §28: retrain a challenger on --
    # -- a schedule; promotion itself always stays a human decision, §12) --
    scheduler.add_job(
        _run, CronTrigger(day_of_week="sun", hour=1, minute=0, timezone=ET),
        args=["historical_dataset_construction", build_historical_dataset.main],
        id="historical_dataset_construction", misfire_grace_time=3600,
    )
    scheduler.add_job(
        _run, CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=ET),
        args=["weekly_training", train_model.main],
        id="weekly_training", misfire_grace_time=3600,
    )
    scheduler.add_job(
        _run, CronTrigger(day_of_week="sun", hour=2, minute=30, timezone=ET),
        args=["challenger_experiment", train_challengers.main],
        id="challenger_experiment", misfire_grace_time=3600,
    )

    return scheduler


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler()
    logger.info("Scheduler starting with %d jobs (timezone=%s)", len(scheduler.get_jobs()), ET)
    scheduler.start()


if __name__ == "__main__":
    main()
