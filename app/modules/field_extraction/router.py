import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.activity_log import ActivityAction, ActivityLog
from app.modules.field_extraction.models import ExtractedField, ExtractedFieldStatus
from app.modules.field_extraction.schemas import (
    ExtractedFieldOut,
    FieldCorrectRequest,
    FieldMismatch,
    MismatchValue,
    ShipmentMismatchOut,
)
from app.modules.user_management.models import User

router = APIRouter(tags=["Field Extraction"])


@router.get("/shipments/{shipment_id}/fields", response_model=list[ExtractedFieldOut])
async def list_fields_for_shipment(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(ExtractedField).where(ExtractedField.shipment_id == shipment_id)
    )
    return list(result.scalars())


@router.get("/documents/{document_id}/fields", response_model=list[ExtractedFieldOut])
async def list_fields_for_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(ExtractedField).where(ExtractedField.document_id == document_id)
    )
    return list(result.scalars())


@router.get("/shipments/{shipment_id}/field-mismatches", response_model=ShipmentMismatchOut)
async def get_shipment_field_mismatches(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Compare extracted field values across all documents in a shipment.
    Returns fields where documents contradict each other.
    severity=error means the discrepancy is customs-critical (weights, currency, HS code, value).
    severity=warning means the discrepancy is notable but less critical.
    """
    from app.modules.field_extraction.service import detect_shipment_mismatches

    raw_mismatches = await detect_shipment_mismatches(shipment_id, db)

    mismatches = [
        FieldMismatch(
            field_name=m["field_name"],
            severity=m["severity"],
            values=[
                MismatchValue(
                    document_id=v["document_id"],
                    value_raw=v["value_raw"],
                    value_normalized=v["value_normalized"],
                    confidence=v["confidence"],
                )
                for v in m["values"]
            ],
        )
        for m in raw_mismatches
    ]

    return ShipmentMismatchOut(shipment_id=shipment_id, mismatches=mismatches)


@router.post("/fields/{field_id}/confirm", response_model=ExtractedFieldOut)
async def confirm_field(
    field_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(ExtractedField).where(ExtractedField.id == field_id))
    field = result.scalar_one_or_none()
    if not field:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")

    field.status = ExtractedFieldStatus.CONFIRMED
    field.confirmed_at = datetime.now(timezone.utc)
    field.confirmed_by = current_user.id

    log_entry = ActivityLog(
        org_id=current_user.org_id,
        shipment_id=field.shipment_id,
        document_id=field.document_id,
        actor_id=current_user.id,
        action=ActivityAction.FIELD_CONFIRMED,
        details={"field_id": str(field_id), "field_name": field.field_name},
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(field)

    # Trigger comparison task if field belongs to a shipment
    if field.shipment_id:
        from app.agents.field_extractor.tasks import run_comparison_task
        run_comparison_task.apply_async(args=[str(field.shipment_id)], queue="classification")

    return field


@router.post("/fields/{field_id}/correct", response_model=ExtractedFieldOut)
async def correct_field(
    field_id: uuid.UUID,
    data: FieldCorrectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(ExtractedField).where(ExtractedField.id == field_id))
    field = result.scalar_one_or_none()
    if not field:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")

    field.status = ExtractedFieldStatus.CORRECTED
    field.corrected_value = data.corrected_value
    field.corrected_by = current_user.id
    field.corrected_at = datetime.now(timezone.utc)

    log_entry = ActivityLog(
        org_id=current_user.org_id,
        shipment_id=field.shipment_id,
        document_id=field.document_id,
        actor_id=current_user.id,
        action=ActivityAction.FIELD_CORRECTED,
        details={
            "field_id": str(field_id),
            "field_name": field.field_name,
            "corrected_value": data.corrected_value,
        },
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(field)

    # Trigger comparison task if field belongs to a shipment
    if field.shipment_id:
        from app.agents.field_extractor.tasks import run_comparison_task
        run_comparison_task.apply_async(args=[str(field.shipment_id)], queue="classification")

    return field
