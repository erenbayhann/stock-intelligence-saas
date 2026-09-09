from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Fundamentals(Base):
    __tablename__ = "fundamentals"
    __table_args__ = (UniqueConstraint("security_id", "period_end", "source"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("securities.id"), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    revenue_growth: Mapped[float | None] = mapped_column(Numeric(8, 4))
    earnings_growth: Mapped[float | None] = mapped_column(Numeric(8, 4))
    eps: Mapped[float | None] = mapped_column(Numeric(10, 4))
    pe_ratio: Mapped[float | None] = mapped_column(Numeric(10, 4))
    price_to_book: Mapped[float | None] = mapped_column(Numeric(10, 4))
    ev_ebitda: Mapped[float | None] = mapped_column(Numeric(10, 4))
    debt_equity: Mapped[float | None] = mapped_column(Numeric(10, 4))
    net_debt_ebitda: Mapped[float | None] = mapped_column(Numeric(10, 4))
    roe: Mapped[float | None] = mapped_column(Numeric(8, 4))
    operating_margin: Mapped[float | None] = mapped_column(Numeric(8, 4))
    free_cash_flow: Mapped[float | None] = mapped_column(Numeric(18, 2))
    market_cap: Mapped[float | None] = mapped_column(Numeric(18, 2))
    dividend_yield: Mapped[float | None] = mapped_column(Numeric(8, 4))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
