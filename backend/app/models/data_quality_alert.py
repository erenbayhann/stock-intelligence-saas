from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DataQualityAlert(Base):
    """Provider errors, missing data, and other anomalies (spec §25) — backs the
    admin panel's "Data quality alerts" card. A job succeeding with a logged
    alert (e.g. one ticker's FMP call 402ing, or one article's LLM extraction
    failing) is the normal pattern — see spec §5's LLM failure handling.
    """

    __tablename__ = "data_quality_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("job_runs.id"))
    severity: Mapped[str] = mapped_column(Text, nullable=False)  # info|warning|error
    # provider_error | missing_data | anomaly | llm_provider_error |
    # champion_performance_degraded | low_credit_balance | ...
    category: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
