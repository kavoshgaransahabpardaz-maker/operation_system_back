"""orchestration_and_source_prefs

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-11 00:00:00.000000

Adds orchestration columns to org_settings and creates org_source_preferences table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- org_settings: orchestration columns ---
    op.add_column(
        "org_settings",
        sa.Column(
            "doc_organization_by",
            sa.String(20),
            nullable=False,
            server_default="shipment",
        ),
    )
    op.add_column(
        "org_settings",
        sa.Column(
            "auto_fix_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.95",
        ),
    )
    op.add_column(
        "org_settings",
        sa.Column(
            "email_critical_alerts",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )

    # --- org_source_preferences table ---
    op.create_table(
        "org_source_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intel_sources.id"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "source_id", name="uq_org_source_pref"),
    )
    op.create_index(
        "ix_org_source_preferences_org_id",
        "org_source_preferences",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_org_source_preferences_org_id", table_name="org_source_preferences")
    op.drop_table("org_source_preferences")
    op.drop_column("org_settings", "email_critical_alerts")
    op.drop_column("org_settings", "auto_fix_threshold")
    op.drop_column("org_settings", "doc_organization_by")
