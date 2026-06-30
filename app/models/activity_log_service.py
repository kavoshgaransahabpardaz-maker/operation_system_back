import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityAction, ActivityLog


def log_activity_sync(
    db: Session,
    org_id: uuid.UUID,
    action: ActivityAction,
    shipment_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        org_id=org_id,
        action=action,
        shipment_id=shipment_id,
        document_id=document_id,
        actor_id=actor_id,
        details=details,
    )
    db.add(entry)
    db.commit()
    return entry


async def log_activity(
    db: AsyncSession,
    org_id: uuid.UUID,
    action: ActivityAction,
    shipment_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        org_id=org_id,
        action=action,
        shipment_id=shipment_id,
        document_id=document_id,
        actor_id=actor_id,
        details=details,
    )
    db.add(entry)
    await db.commit()
    return entry


async def get_activity_log(
    db: AsyncSession,
    org_id: uuid.UUID,
    shipment_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[ActivityLog]:
    query = select(ActivityLog).where(ActivityLog.org_id == org_id)
    if shipment_id:
        query = query.where(ActivityLog.shipment_id == shipment_id)
    query = query.order_by(ActivityLog.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
