from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobRun(Base):
    """One row per background job execution (spec §20/§25) — backs the admin
    panel's "Job health" card and GET /api/v1/health's per-job status.
    """

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)  # running|success|failed
    error_message: Mapped[str | None] = mapped_column(Text)
    # For job_name='news_ingestion' also carries LLM cost for that run, per spec §5:
    # {"llm_tokens_in": N, "llm_tokens_out": N, "llm_cost_usd": N}
    job_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
