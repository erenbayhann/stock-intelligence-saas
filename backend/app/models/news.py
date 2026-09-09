from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (UniqueConstraint("source", "source_article_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_article_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sentiment: Mapped[float | None] = mapped_column(Numeric(4, 3))
    event_category: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[float | None] = mapped_column(Numeric(4, 3))
    is_duplicate_of: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("news_articles.id")
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)


class NewsCompanyLink(Base):
    __tablename__ = "news_company_links"
    __table_args__ = (UniqueConstraint("news_article_id", "security_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    news_article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_articles.id"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("securities.id"), nullable=False)
    relevance: Mapped[float | None] = mapped_column(Numeric(4, 3))
