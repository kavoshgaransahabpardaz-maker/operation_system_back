"""Hasti features: email keywords, org OCR languages

Revision ID: f2a3b4c5d6e7
Revises: e5f6a7b8c9d0
Create Date: 2026-07-13

"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # email_keywords on mailbox_connections — nullable, no default row value
    op.add_column(
        "mailbox_connections",
        sa.Column(
            "email_keywords",
            postgresql.ARRAY(sa.String(500)),
            nullable=True,
        ),
    )

    # ocr_languages on org_settings — new rows default to "eng"
    op.add_column(
        "org_settings",
        sa.Column(
            "ocr_languages",
            sa.String(200),
            nullable=False,
            server_default="eng",
        ),
    )


def downgrade() -> None:
    op.drop_column("org_settings", "ocr_languages")
    op.drop_column("mailbox_connections", "email_keywords")
