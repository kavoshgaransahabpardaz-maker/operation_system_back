"""article_feedback

Revision ID: f1a2b3c4d5e6
Revises: ae2e3e3cb71a
Create Date: 2026-07-08 00:00:00.000000

Adds article_feedback table for per-user like/dislike on intel articles.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "ae2e3e3cb71a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "article_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intel_articles.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("feedback", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("article_id", "user_id", name="uq_article_feedback_article_user"),
    )
    op.create_index("ix_article_feedback_article_id", "article_feedback", ["article_id"])
    op.create_index("ix_article_feedback_org_id", "article_feedback", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_article_feedback_org_id", table_name="article_feedback")
    op.drop_index("ix_article_feedback_article_id", table_name="article_feedback")
    op.drop_table("article_feedback")
