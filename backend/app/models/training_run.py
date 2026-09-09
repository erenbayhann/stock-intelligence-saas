from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    train_window_start: Mapped[date] = mapped_column(Date, nullable=False)
    train_window_end: Mapped[date] = mapped_column(Date, nullable=False)
    validation_window_start: Mapped[date] = mapped_column(Date, nullable=False)
    validation_window_end: Mapped[date] = mapped_column(Date, nullable=False)
    test_window_start: Mapped[date | None] = mapped_column(Date)
    test_window_end: Mapped[date | None] = mapped_column(Date)
    resulting_model_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)  # running|completed|failed
    notes: Mapped[str | None] = mapped_column(Text)
