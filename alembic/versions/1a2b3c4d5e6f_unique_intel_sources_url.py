"""Add unique constraint on intel_sources.url to prevent duplicate sources

Revision ID: 1a2b3c4d5e6f
Revises: c7d8e9f0a1b2
Create Date: 2026-07-22

"""
from typing import Union
from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_intel_sources_url", "intel_sources", ["url"])


def downgrade() -> None:
    op.drop_constraint("uq_intel_sources_url", "intel_sources", type_="unique")
