"""Add document_products table for classification API results

Revision ID: 3dfa2c7a2a98
Revises: f2a3b4c5d6e7, a1b2c3d4e5f6
Create Date: 2026-07-16

Merges hasti_features (f2a3b4c5d6e7) and orchestration_and_source_prefs (a1b2c3d4e5f6) branches.
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3dfa2c7a2a98"
down_revision: Union[str, tuple] = ("f2a3b4c5d6e7", "a1b2c3d4e5f6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shipments.id"), nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("material", sa.Text(), nullable=True),
        sa.Column("intended_use", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.String(100), nullable=True),
        sa.Column("unit_price", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("origin_country", sa.String(10), nullable=True),
        sa.Column("destination_country", sa.String(10), nullable=True),
        sa.Column("existing_hs_code", sa.String(20), nullable=True),
        sa.Column("missing_required_fields", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_ready_to_classify", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_document_products_document_id", "document_products", ["document_id"])
    op.create_index("ix_document_products_shipment_id", "document_products", ["shipment_id"])
    op.create_index("ix_document_products_org_id", "document_products", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_document_products_org_id", table_name="document_products")
    op.drop_index("ix_document_products_shipment_id", table_name="document_products")
    op.drop_index("ix_document_products_document_id", table_name="document_products")
    op.drop_table("document_products")
