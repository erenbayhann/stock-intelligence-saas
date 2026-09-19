"""news picks: a daily, locked-before-the-open news-only top-5, with results

The News page used to be a rolling digest of individually-scored
headlines. It is now a second, independent daily pick list that follows the
ranking model's exact cycle (locked ~09:15 ET, immutable, evaluated after
the close) but ranks stocks purely by how much net-positive classified
news landed since the previous close.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_pick_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("target_session_date", sa.Date, nullable=False, unique=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidates_scored", sa.Integer, nullable=False),
    )
    op.create_table(
        "news_picks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("news_pick_runs.id"), nullable=False),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("rank", sa.SmallInteger, nullable=False),
        sa.Column("news_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("article_count", sa.Integer, nullable=False),
        sa.Column("positive_count", sa.Integer, nullable=False),
        sa.Column("negative_count", sa.Integer, nullable=False),
        sa.Column("avg_sentiment", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint("run_id", "security_id"),
        sa.UniqueConstraint("run_id", "rank"),
    )
    op.create_table(
        "news_pick_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "pick_id", sa.BigInteger, sa.ForeignKey("news_picks.id"), nullable=False, unique=True
        ),
        sa.Column("actual_return", sa.Numeric(8, 5), nullable=False),
        sa.Column("benchmark_return", sa.Numeric(8, 5), nullable=False),
        sa.Column("excess_return", sa.Numeric(8, 5), nullable=False),
        sa.Column("hit", sa.Boolean, nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("news_pick_results")
    op.drop_table("news_picks")
    op.drop_table("news_pick_runs")
