from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PredictionRun(Base):
    __tablename__ = "prediction_runs"
    __table_args__ = (
        Index(
            "idx_one_final_run_per_day",
            "target_session_date",
            unique=True,
            postgresql_where=text("run_type = 'final'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_versions.id"), nullable=False
    )
    run_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'draft' | 'final'
    target_session_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="completed")


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("prediction_run_id", "security_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prediction_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prediction_runs.id"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("securities.id"), nullable=False)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1..5
    ai_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    raw_predicted_excess_return: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)  # High|Medium|Low
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    feature_snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("feature_snapshots.id"), nullable=False
    )
    price_at_prediction: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PredictionNewsLink(Base):
    __tablename__ = "prediction_news_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("predictions.id"), nullable=False
    )
    news_article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_articles.id"), nullable=False
    )


class PredictionResult(Base):
    __tablename__ = "prediction_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("predictions.id"), nullable=False, unique=True
    )
    actual_return: Mapped[float | None] = mapped_column(Numeric(8, 5))
    benchmark_return: Mapped[float | None] = mapped_column(Numeric(8, 5))
    actual_excess_return: Mapped[float | None] = mapped_column(Numeric(8, 5))
    prediction_error: Mapped[float | None] = mapped_column(Numeric(8, 5))
    direction_correct: Mapped[bool | None] = mapped_column(Boolean)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
