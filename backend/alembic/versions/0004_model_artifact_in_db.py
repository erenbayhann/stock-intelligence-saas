"""store trained model artifacts in the database instead of local disk

Discovered live on Railway (2026-09-16): the backend service has no
persistent local disk (no Volume attached), and each Console command runs
in its own fresh, ephemeral container instance — matching `docker compose
run` locally, not the always-on `docker compose up` replica. A model
trained via `train_model`/`train_challengers` wrote its .joblib artifact
to that ephemeral container's own local /srv/ml_artifacts/, which no
longer existed by the time a later command (generate_predictions, in a
different fresh container) tried to load it — a real
"NoChampionModelError: Champion model artifact missing on disk" in
production, not a local-dev-only quirk. Postgres is the only thing every
one of these ephemeral containers actually shares, so the fix is to store
the serialized pipeline directly as a column, not a file path.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("artifact", sa.LargeBinary))


def downgrade() -> None:
    op.drop_column("model_versions", "artifact")
