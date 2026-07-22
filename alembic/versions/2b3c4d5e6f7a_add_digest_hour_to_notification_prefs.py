"""Add digest_hour to notification_preferences for daily email digest scheduling

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-22

"""
from typing import Union
import sqlalchemy as sa
from alembic import op

revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import text
    conn = op.get_bind()
    cols = [row[0] for row in conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='notification_preferences'"
    ))]
    if "digest_hour" not in cols:
        op.add_column(
            "notification_preferences",
            sa.Column("digest_hour", sa.Integer(), nullable=False, server_default="8"),
        )


def downgrade() -> None:
    op.drop_column("notification_preferences", "digest_hour")
