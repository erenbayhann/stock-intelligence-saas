"""initial schema — full table set per docs/api-and-schema-plan.md

Revision ID: 0001
Revises:
Create Date: 2026-09-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("cik", sa.Text, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("sector", sa.Text),
        sa.Column("industry", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "securities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.BigInteger, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("ticker", sa.Text, nullable=False, unique=True),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "added_to_universe_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("removed_from_universe_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_securities_ticker", "securities", ["ticker"])

    op.create_table(
        "news_articles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_article_id", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("published_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("sentiment", sa.Numeric(4, 3)),
        sa.Column("event_category", sa.Text),
        sa.Column("importance", sa.Numeric(4, 3)),
        sa.Column("is_duplicate_of", sa.BigInteger, sa.ForeignKey("news_articles.id")),
        sa.Column("raw_payload", postgresql.JSONB),
        sa.UniqueConstraint("source", "source_article_id"),
    )
    op.create_index("idx_news_published_time", "news_articles", ["published_time"])

    op.create_table(
        "news_company_links",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("news_article_id", sa.BigInteger, sa.ForeignKey("news_articles.id"), nullable=False),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("relevance", sa.Numeric(4, 3)),
        sa.UniqueConstraint("news_article_id", "security_id"),
    )

    op.create_table(
        "market_prices",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_type", sa.Text, nullable=False),
        sa.Column("open", sa.Numeric(14, 4), nullable=False),
        sa.Column("high", sa.Numeric(14, 4), nullable=False),
        sa.Column("low", sa.Numeric(14, 4), nullable=False),
        sa.Column("close", sa.Numeric(14, 4), nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column(
            "received_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("security_id", "ts", "session_type", "source"),
    )
    op.create_index("idx_market_prices_security_ts", "market_prices", ["security_id", "ts"])

    op.create_table(
        "fundamentals",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("revenue_growth", sa.Numeric(8, 4)),
        sa.Column("earnings_growth", sa.Numeric(8, 4)),
        sa.Column("eps", sa.Numeric(10, 4)),
        sa.Column("pe_ratio", sa.Numeric(10, 4)),
        sa.Column("price_to_book", sa.Numeric(10, 4)),
        sa.Column("ev_ebitda", sa.Numeric(10, 4)),
        sa.Column("debt_equity", sa.Numeric(10, 4)),
        sa.Column("net_debt_ebitda", sa.Numeric(10, 4)),
        sa.Column("roe", sa.Numeric(8, 4)),
        sa.Column("operating_margin", sa.Numeric(8, 4)),
        sa.Column("free_cash_flow", sa.Numeric(18, 2)),
        sa.Column("market_cap", sa.Numeric(18, 2)),
        sa.Column("dividend_yield", sa.Numeric(8, 4)),
        sa.Column("raw_payload", postgresql.JSONB),
        sa.UniqueConstraint("security_id", "period_end", "source"),
    )
    op.create_index("idx_fundamentals_filed_at", "fundamentals", ["security_id", "filed_at"])

    op.create_table(
        "filings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("filing_type", sa.Text, nullable=False),
        sa.Column("accession_number", sa.Text, nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_of_report", sa.Date),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default="sec_edgar"),
        sa.Column("raw_payload", postgresql.JSONB),
        sa.Column(
            "received_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("security_id", "accession_number"),
    )
    op.create_index("idx_filings_filed_at", "filings", ["security_id", "filed_at"])

    op.create_table(
        "macro_data",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("series_id", sa.Text, nullable=False),
        sa.Column("observation_date", sa.Date, nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("realtime_start", sa.Date, nullable=False),
        sa.Column("realtime_end", sa.Date, nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default="fred"),
        sa.UniqueConstraint("series_id", "observation_date", "realtime_start"),
    )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_label", sa.Text, nullable=False, unique=True),
        sa.Column("algorithm", sa.Text, nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.Column("hyperparameters", postgresql.JSONB),
        sa.Column("metrics", postgresql.JSONB),
    )

    op.create_table(
        "training_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("train_window_start", sa.Date, nullable=False),
        sa.Column("train_window_end", sa.Date, nullable=False),
        sa.Column("validation_window_start", sa.Date, nullable=False),
        sa.Column("validation_window_end", sa.Date, nullable=False),
        sa.Column("test_window_start", sa.Date),
        sa.Column("test_window_end", sa.Date),
        sa.Column("resulting_model_version_id", sa.BigInteger, sa.ForeignKey("model_versions.id")),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("idx_feature_snapshots_security_asof", "feature_snapshots", ["security_id", "as_of"])

    op.create_table(
        "prediction_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version_id", sa.BigInteger, sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("run_type", sa.Text, nullable=False),
        sa.Column("target_session_date", sa.Date, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="completed"),
    )
    op.create_index(
        "idx_one_final_run_per_day",
        "prediction_runs",
        ["target_session_date"],
        unique=True,
        postgresql_where=sa.text("run_type = 'final'"),
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("prediction_run_id", sa.BigInteger, sa.ForeignKey("prediction_runs.id"), nullable=False),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("rank", sa.SmallInteger, nullable=False),
        sa.Column("ai_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("raw_predicted_excess_return", sa.Numeric(8, 5), nullable=False),
        sa.Column("confidence", sa.Text, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column(
            "feature_snapshot_id", sa.BigInteger, sa.ForeignKey("feature_snapshots.id"), nullable=False
        ),
        sa.Column("price_at_prediction", sa.Numeric(14, 4), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("prediction_run_id", "security_id"),
    )

    op.create_table(
        "prediction_news_links",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("prediction_id", sa.BigInteger, sa.ForeignKey("predictions.id"), nullable=False),
        sa.Column("news_article_id", sa.BigInteger, sa.ForeignKey("news_articles.id"), nullable=False),
    )

    op.create_table(
        "prediction_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "prediction_id", sa.BigInteger, sa.ForeignKey("predictions.id"), nullable=False, unique=True
        ),
        sa.Column("actual_return", sa.Numeric(8, 5)),
        sa.Column("benchmark_return", sa.Numeric(8, 5)),
        sa.Column("actual_excess_return", sa.Numeric(8, 5)),
        sa.Column("prediction_error", sa.Numeric(8, 5)),
        sa.Column("direction_correct", sa.Boolean),
        sa.Column("evaluated_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text),
        sa.Column("tier", sa.Text, nullable=False, server_default="free"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("prediction_results")
    op.drop_table("prediction_news_links")
    op.drop_table("predictions")
    op.drop_index("idx_one_final_run_per_day", table_name="prediction_runs")
    op.drop_table("prediction_runs")
    op.drop_index("idx_feature_snapshots_security_asof", table_name="feature_snapshots")
    op.drop_table("feature_snapshots")
    op.drop_table("training_runs")
    op.drop_table("model_versions")
    op.drop_table("macro_data")
    op.drop_index("idx_filings_filed_at", table_name="filings")
    op.drop_table("filings")
    op.drop_index("idx_fundamentals_filed_at", table_name="fundamentals")
    op.drop_table("fundamentals")
    op.drop_index("idx_market_prices_security_ts", table_name="market_prices")
    op.drop_table("market_prices")
    op.drop_table("news_company_links")
    op.drop_index("idx_news_published_time", table_name="news_articles")
    op.drop_table("news_articles")
    op.drop_index("idx_securities_ticker", table_name="securities")
    op.drop_table("securities")
    op.drop_table("companies")
