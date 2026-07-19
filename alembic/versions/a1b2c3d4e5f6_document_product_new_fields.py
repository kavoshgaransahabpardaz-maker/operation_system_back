"""Add new fields to document_products from updated classification API

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-07-19

"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_products", sa.Column("line_total", sa.String(50), nullable=True))
    op.add_column("document_products", sa.Column("ship_from", sa.Text(), nullable=True))
    op.add_column("document_products", sa.Column("existing_national_code", sa.String(30), nullable=True))
    op.add_column("document_products", sa.Column("existing_national_code_jurisdiction", sa.String(10), nullable=True))
    op.add_column("document_products", sa.Column("lot_number", sa.String(100), nullable=True))
    op.add_column("document_products", sa.Column("expiry_date", sa.String(30), nullable=True))
    op.add_column("document_products", sa.Column("net_weight", sa.String(50), nullable=True))
    op.add_column("document_products", sa.Column("gross_weight", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("document_products", "gross_weight")
    op.drop_column("document_products", "net_weight")
    op.drop_column("document_products", "expiry_date")
    op.drop_column("document_products", "lot_number")
    op.drop_column("document_products", "existing_national_code_jurisdiction")
    op.drop_column("document_products", "existing_national_code")
    op.drop_column("document_products", "ship_from")
    op.drop_column("document_products", "line_total")
