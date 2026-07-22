"""Add unique constraint on intel_sources.url to prevent duplicate sources

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-07-22

"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_intel_sources_url", "intel_sources", ["url"])


def downgrade() -> None:
    op.drop_constraint("uq_intel_sources_url", "intel_sources", type_="unique")
