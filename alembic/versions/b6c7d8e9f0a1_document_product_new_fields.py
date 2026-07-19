"""Add new fields to document_products from updated classification API

Revision ID: b6c7d8e9f0a1
Revises: 4e8f1b2c3d9a
Create Date: 2026-07-19

"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "4e8f1b2c3d9a"
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
