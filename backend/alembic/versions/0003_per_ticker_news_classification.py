"""move sentiment/event_category/importance from news_articles to news_company_links, add news_articles.classified_at

Spec update (2026-09-14): the LLM extraction step used to classify a single
(article, first-linked-company) pair and store sentiment/event_category/
importance on the ARTICLE row — meaning every company linked to a
multi-company article shared one sentiment value, even when the news is
clearly not equally valenced for all of them (e.g. an M&A article should
read differently for the acquirer vs. the target). Moving these three
columns onto news_company_links makes them genuinely per-(article,ticker),
which is also what a new full-universe classification pass needs (see
app/services/news_service.py) to do real content/sector-based ticker
inference instead of literal company-name substring matching alone.
classified_at on news_articles tracks whether that pass has run for a
given article, independent of how many (or zero) tickers it ends up
linking to.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("news_company_links", sa.Column("sentiment", sa.Numeric(4, 3)))
    op.add_column("news_company_links", sa.Column("event_category", sa.Text))
    op.add_column("news_company_links", sa.Column("importance", sa.Numeric(4, 3)))
    op.add_column("news_articles", sa.Column("classified_at", sa.DateTime(timezone=True)))

    op.drop_column("news_articles", "sentiment")
    op.drop_column("news_articles", "event_category")
    op.drop_column("news_articles", "importance")


def downgrade() -> None:
    op.add_column("news_articles", sa.Column("sentiment", sa.Numeric(4, 3)))
    op.add_column("news_articles", sa.Column("event_category", sa.Text))
    op.add_column("news_articles", sa.Column("importance", sa.Numeric(4, 3)))
    op.drop_column("news_articles", "classified_at")

    op.drop_column("news_company_links", "sentiment")
    op.drop_column("news_company_links", "event_category")
    op.drop_column("news_company_links", "importance")
