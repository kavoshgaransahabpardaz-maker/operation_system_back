"""add_missing_enum_values

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-11 00:00:00.000000

Adds enum values missing from the initial migration:
- activityaction: FIELD_EXTRACTED, FIELD_CONFIRMED, FIELD_CORRECTED,
                  FLAG_CREATED, FLAG_RESOLVED, COMPARISON_RUN, SETTINGS_UPDATED
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'FIELD_EXTRACTED'")
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'FIELD_CONFIRMED'")
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'FIELD_CORRECTED'")
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'FLAG_CREATED'")
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'FLAG_RESOLVED'")
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'COMPARISON_RUN'")
    op.execute("ALTER TYPE activityaction ADD VALUE IF NOT EXISTS 'SETTINGS_UPDATED'")


def downgrade() -> None:
    pass
