from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiCreditTopup(Base):
    """Manual record of a top-up to the (prepaid, balance-unqueryable) Anthropic
    API account — spec §15's LLM/API credit balance admin card is computed from
    the sum of these minus logged spend in job_runs.metadata.
    """

    __tablename__ = "api_credit_topups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    topped_up_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
