from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsPickRun(Base):
    """One immutable, locked-before-the-open snapshot of the news-only top
    picks for a target session (mirrors prediction_runs, spec §11) —
    generated_at is when the row was written, as_of is the information
    cutoff (only news classified at or before it was used). They differ
    only for a run reconstructed after the fact.
    """

    __tablename__ = "news_pick_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_session_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candidates_scored: Mapped[int] = mapped_column(Integer, nullable=False)


class NewsPick(Base):
    __tablename__ = "news_picks"
    __table_args__ = (
        UniqueConstraint("run_id", "security_id"),
        UniqueConstraint("run_id", "rank"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("news_pick_runs.id"), nullable=False)
    security_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("securities.id"), nullable=False)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Sum over the window of sentiment x importance x relevance.
    news_score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_sentiment: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    # Snapshot of the headlines behind the score, frozen at lock time.
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False)


class NewsPickResult(Base):
    """Written once after the session closes, never updated (mirrors
    prediction_results, spec §13)."""

    __tablename__ = "news_pick_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pick_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_picks.id"), nullable=False, unique=True
    )
    actual_return: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False)
    benchmark_return: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False)
    excess_return: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False)
    # A bullish pick is "correct" when it beat the benchmark that session —
    # the same yardstick as the ranking model's direction_correct.
    hit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
