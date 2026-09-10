import pytest
from sqlalchemy import select

from app.models.job_run import JobRun
from app.services.job_run_service import track_job_run


def test_track_job_run_records_success(db_session):
    with track_job_run(db_session, "market_data_ingestion") as job_run:
        job_run.job_metadata = {"rows_written": 5}

    row = db_session.scalar(select(JobRun))
    assert row.job_name == "market_data_ingestion"
    assert row.status == "success"
    assert row.finished_at is not None
    assert row.job_metadata == {"rows_written": 5}


def test_track_job_run_records_failure_and_reraises(db_session):
    with pytest.raises(ValueError, match="boom"):
        with track_job_run(db_session, "news_ingestion"):
            raise ValueError("boom")

    row = db_session.scalar(select(JobRun))
    assert row.status == "failed"
    assert row.error_message == "boom"
    assert row.finished_at is not None


def test_track_job_run_rolls_back_partial_work_on_failure(db_session):
    """Regression test for a real bug: a crash partway through a job used to
    leave whatever had been flushed-but-not-committed permanently in the
    database (the failure handler called commit(), not rollback()) — a
    prediction_runs row was found with status='completed' and zero
    predictions under it after exactly this kind of mid-job crash.
    """
    from app.models.company import Company

    with pytest.raises(ValueError, match="boom"):
        with track_job_run(db_session, "prediction_generation"):
            db_session.add(Company(name="Should not survive the crash"))
            db_session.flush()  # visible in this transaction, but not yet committed
            raise ValueError("boom")

    orphaned = db_session.scalar(select(Company).where(Company.name == "Should not survive the crash"))
    assert orphaned is None  # rolled back, not persisted

    job_run = db_session.scalar(select(JobRun))
    assert job_run.status == "failed"  # the job_run row itself still gets recorded correctly
