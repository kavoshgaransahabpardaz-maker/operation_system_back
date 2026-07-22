"""Add hs_genie_runs table and hs-verification fields to document_products

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-07-22

"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hs_genie_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("document_products.id"), nullable=False, index=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(10), nullable=False),
        sa.Column("record_id", sa.String(100), nullable=True),
        sa.Column("candidates", postgresql.JSON, nullable=True),
        sa.Column("input_text", sa.Text, nullable=True),
        sa.Column("chosen_code", sa.String(20), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chosen_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feedback_signal", sa.String(20), nullable=True),
        sa.Column("corrected_code", sa.String(20), nullable=True),
        sa.Column("correction_reason", sa.String(100), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("document_products", sa.Column("hs_verified", sa.Boolean, nullable=True, server_default="false"))
    op.add_column("document_products", sa.Column("hs_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_products", sa.Column("hs_verified_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("document_products", sa.Column("active_genie_run_id", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("document_products", "active_genie_run_id")
    op.drop_column("document_products", "hs_verified_by")
    op.drop_column("document_products", "hs_verified_at")
    op.drop_column("document_products", "hs_verified")
    op.drop_table("hs_genie_runs")
