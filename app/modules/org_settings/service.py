"""
Org settings service.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.org_settings.models import OrgSettings


async def get_settings(org_id: uuid.UUID, db: AsyncSession) -> OrgSettings:
    """Return existing OrgSettings row, or an in-memory default (does not create a row)."""
    result = await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    settings_row = result.scalar_one_or_none()
    if settings_row:
        return settings_row

    # Return a transient default object — not persisted
    return OrgSettings(
        org_id=org_id,
        weight_qty_tolerance_pct=0.5,
        value_tolerance_pct=1.0,
        name_match_threshold=0.93,
    )


async def upsert_settings(org_id: uuid.UUID, data: dict, db: AsyncSession) -> OrgSettings:
    """INSERT or UPDATE org settings."""
    result = await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    existing = result.scalar_one_or_none()

    if existing:
        for key, value in data.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return existing

    new_settings = OrgSettings(org_id=org_id, **data)
    db.add(new_settings)
    await db.commit()
    await db.refresh(new_settings)
    return new_settings
