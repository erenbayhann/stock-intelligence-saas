from datetime import date

from sqlalchemy import BigInteger, Date, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MacroData(Base):
    __tablename__ = "macro_data"
    __table_args__ = (UniqueConstraint("series_id", "observation_date", "realtime_start"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(Text, nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    realtime_start: Mapped[date] = mapped_column(Date, nullable=False)
    realtime_end: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="fred")
