"""Add bill_of_material and product_specification to documenttype enum

Revision ID: 4e8f1b2c3d9a
Revises: 3dfa2c7a2a98
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "4e8f1b2c3d9a"
down_revision: Union[str, None] = "3dfa2c7a2a98"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE documenttype ADD VALUE IF NOT EXISTS 'BILL_OF_MATERIAL'")
    op.execute("ALTER TYPE documenttype ADD VALUE IF NOT EXISTS 'PRODUCT_SPECIFICATION'")


def downgrade() -> None:
    pass
