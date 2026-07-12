"""add_super_admin_role

Revision ID: e5f6a7b8c9d0
Revises: f1a2b3c4d5e6
Create Date: 2026-07-13 00:00:00.000000

Adds SUPER_ADMIN value to the userrole PostgreSQL enum.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'SUPER_ADMIN'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    pass
