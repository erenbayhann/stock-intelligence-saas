"""drop users table, add model_versions.feature_set, add job_runs/api_credit_topups/data_quality_alerts

Spec update (2026-09-10): product has no user accounts at all (§16) — admin
auth is a single env-var credential, not a DB-backed users table. Adds the
admin-panel observability tables (§15/§17) and the feature_set column that
lets two parallel model lineages (news-free / news-inclusive, §12) share
model_versions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("users")

    op.add_column(
        "model_versions",
        sa.Column("feature_set", sa.Text, nullable=False, server_default="price_fundamentals_macro"),
    )
    op.alter_column("model_versions", "feature_set", server_default=None)

    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("job_name", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("metadata", postgresql.JSONB),
    )
    op.create_index("idx_job_runs_name_started", "job_runs", ["job_name", sa.text("started_at DESC")])

    op.create_table(
        "api_credit_topups",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("topped_up_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )

    op.create_table(
        "data_quality_alerts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("job_run_id", sa.BigInteger, sa.ForeignKey("job_runs.id")),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("detail", postgresql.JSONB),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_dq_alerts_created", "data_quality_alerts", [sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_dq_alerts_created", table_name="data_quality_alerts")
    op.drop_table("data_quality_alerts")
    op.drop_table("api_credit_topups")
    op.drop_index("idx_job_runs_name_started", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_column("model_versions", "feature_set")

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
