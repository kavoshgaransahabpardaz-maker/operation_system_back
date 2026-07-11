"""phytosanitary_certificate

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-11 00:00:00.000000

Adds phytosanitary_certificate value to documenttype enum.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires this outside a transaction block for older versions.
    # IF NOT EXISTS is safe to run repeatedly.
    op.execute("ALTER TYPE documenttype ADD VALUE IF NOT EXISTS 'PHYTOSANITARY_CERTIFICATE'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
