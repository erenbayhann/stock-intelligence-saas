import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy.orm import Session

from app.models.job_run import JobRun

logger = logging.getLogger(__name__)


@contextmanager
def track_job_run(db: Session, job_name: str) -> Iterator[JobRun]:
    """Records one job_runs row for the duration of a background job (spec
    §20/§25) — backs the admin panel's "Job health" card and GET /api/v1/health.

    On success the row's status becomes 'success'. On an exception, status
    becomes 'failed' with error_message set, and the exception is re-raised
    unchanged — job_runs tracking never swallows a real failure, it only
    records it so it's visible without digging through logs.
    """
    job_run = JobRun(
        job_name=job_name,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.add(job_run)
    db.commit()

    try:
        yield job_run
    except Exception as exc:
        job_run.status = "failed"
        job_run.error_message = str(exc)
        job_run.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.exception("Job %s failed", job_name)
        raise
    else:
        job_run.status = "success"
        job_run.finished_at = datetime.now(timezone.utc)
        db.commit()
