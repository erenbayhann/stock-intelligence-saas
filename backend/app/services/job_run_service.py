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

    On success the row's status becomes 'success'. On an exception, any
    uncommitted application-level work from the failed job is ROLLED BACK
    first — a job that crashes partway through must never leave a partial,
    half-written row behind (spec §11's immutable snapshots must be complete
    when published, never a crashed-mid-write fragment) — then status
    becomes 'failed' with error_message set in a fresh transaction, and the
    exception is re-raised unchanged. Hit this as a real bug: an early
    version called db.commit() instead of db.rollback() here, and a crash
    partway through prediction generation left a prediction_runs row
    labeled status='completed' in the database with zero predictions under
    it, because the job's own uncommitted `flush()`es got swept in by this
    handler's commit.
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
        db.rollback()  # discard partial application-level work from the failed job
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
