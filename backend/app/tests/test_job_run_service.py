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
