"""
Flags service — runs comparison engine, persists flags, handles resolutions.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityAction, ActivityLog
from app.modules.field_extraction.models import ExtractedField
from app.modules.flags.models import Flag, FlagResolution, FlagStatus, ResolutionDecision
from app.modules.mismatch.engine import compare_shipment_fields
from app.modules.org_settings.service import get_settings

logger = logging.getLogger(__name__)


async def run_comparison_and_create_flags(shipment_id: uuid.UUID, db: AsyncSession) -> None:
    """Load fields for shipment, run mismatch engine, persist new flags."""

    # 1. Load all extracted/confirmed/corrected fields for this shipment
    fields_result = await db.execute(
        select(ExtractedField).where(ExtractedField.shipment_id == shipment_id)
    )
    fields = list(fields_result.scalars())

    if not fields:
        logger.info("No extracted fields for shipment %s — skipping comparison", shipment_id)
        return

    # Determine org_id from first field
    org_id = fields[0].org_id

    # 2. Load org settings (or in-memory defaults)
    settings = await get_settings(org_id, db) if org_id else None

    # 3. Run pure mismatch engine
    flag_specs = compare_shipment_fields(fields, settings)

    # 4. Persist new flags (skip identical open flags)
    created_count = 0
    for spec in flag_specs:
        # Deduplication: skip if an open flag with same type+title exists
        existing_result = await db.execute(
            select(Flag).where(
                Flag.shipment_id == shipment_id,
                Flag.flag_type == spec.flag_type,
                Flag.title == spec.title,
                Flag.status == FlagStatus.OPEN,
            )
        )
        if existing_result.scalar_one_or_none():
            continue

        flag = Flag(
            shipment_id=shipment_id,
            org_id=org_id,
            flag_type=spec.flag_type,
            severity=spec.severity,
            title=spec.title,
            description=spec.description,
            conflicting_values=spec.conflicting_values,
            status=FlagStatus.OPEN,
        )
        db.add(flag)
        created_count += 1

    # 5. Log COMPARISON_RUN
    log_entry = ActivityLog(
        org_id=org_id,
        shipment_id=shipment_id,
        action=ActivityAction.COMPARISON_RUN,
        details={"flags_created": created_count, "total_specs": len(flag_specs)},
    )
    db.add(log_entry)

    await db.commit()
    logger.info(
        "Comparison run for shipment %s: %d new flags created out of %d specs",
        shipment_id, created_count, len(flag_specs),
    )


async def resolve_flag(
    flag_id: uuid.UUID,
    user_id: uuid.UUID,
    decision: str,
    chosen_value: str | None,
    note: str | None,
    db: AsyncSession,
) -> Flag:
    """Append a FlagResolution and mark the flag resolved."""

    # 1. Load flag and check it exists
    flag_result = await db.execute(select(Flag).where(Flag.id == flag_id))
    flag = flag_result.scalar_one_or_none()
    if not flag:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")

    # 2. INSERT FlagResolution (append-only — never update)
    resolution = FlagResolution(
        flag_id=flag_id,
        resolved_by=user_id,
        decision=ResolutionDecision(decision),
        chosen_value=chosen_value,
        note=note,
    )
    db.add(resolution)

    # 3. UPDATE flag status
    flag.status = FlagStatus.RESOLVED
    flag.resolved_at = datetime.now(timezone.utc)

    # 4. Log FLAG_RESOLVED
    log_entry = ActivityLog(
        org_id=flag.org_id,
        shipment_id=flag.shipment_id,
        actor_id=user_id,
        action=ActivityAction.FLAG_RESOLVED,
        details={"flag_id": str(flag_id), "decision": decision},
    )
    db.add(log_entry)

    await db.commit()
    await db.refresh(flag)
    return flag
