from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.job_run import JobRun
from app.models.market_price import MarketPrice
from app.models.security import Security

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness/readiness check (spec §25, api-and-schema-plan.md §1): confirms
    DB reachability and reports the last run of every distinct job_name in
    job_runs, plus basic universe/data-freshness signals, so ingestion
    problems are visible without digging through logs.
    """
    db_ok = True
    active_securities = 0
    latest_market_price_at = None
    jobs: list[dict] = []
    try:
        active_securities = db.scalar(
            select(func.count()).select_from(Security).where(Security.is_active.is_(True))
        )
        latest_market_price_at = db.scalar(select(func.max(MarketPrice.ts)))

        latest_per_job = (
            select(JobRun)
            .distinct(JobRun.job_name)
            .order_by(JobRun.job_name, JobRun.started_at.desc())
        )
        jobs = [
            {
                "job_name": row.job_name,
                "status": row.status,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
            }
            for row in db.scalars(latest_per_job)
        ]
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "database": "reachable" if db_ok else "unreachable",
        "active_securities": active_securities,
        "latest_market_price_at": latest_market_price_at,
        "jobs": jobs,
    }
