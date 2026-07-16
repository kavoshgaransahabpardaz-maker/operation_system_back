import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.activity_log import ActivityAction, ActivityLog
from app.modules.classification_api.models import DocumentProduct
from app.modules.field_extraction.models import ExtractedField, ExtractedFieldStatus
from app.modules.field_extraction.schemas import (
    ExtractedFieldOut,
    FieldCorrectRequest,
    FieldMismatch,
    MismatchValue,
    ProductFieldMismatch,
    ProductGroupMismatch,
    ProductMismatchValue,
    ShipmentMismatchOut,
    UnmatchedProduct,
)
from app.modules.user_management.models import User


class DocumentProductOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    shipment_id: uuid.UUID | None
    org_id: uuid.UUID
    product_name: str | None
    material: str | None
    intended_use: str | None
    description: str | None
    quantity: str | None
    unit_price: str | None
    currency: str | None
    origin_country: str | None
    destination_country: str | None
    existing_hs_code: str | None
    missing_required_fields: list | None
    is_ready_to_classify: bool
    created_at: datetime

    model_config = {"from_attributes": True}

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


@router.get("/documents/{document_id}/products", response_model=list[DocumentProductOut])
async def list_products_for_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return the product lines extracted by the classification API for a document."""
    result = await db.execute(
        select(DocumentProduct).where(DocumentProduct.document_id == document_id)
    )
    return list(result.scalars())


@router.get("/shipments/{shipment_id}/products", response_model=list[DocumentProductOut])
async def list_products_for_shipment(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return all product lines across all documents in a shipment."""
    result = await db.execute(
        select(DocumentProduct).where(DocumentProduct.shipment_id == shipment_id)
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


@router.post("/shipments/{shipment_id}/fields/confirm-all", response_model=dict)
async def confirm_all_fields_for_shipment(
    shipment_id: uuid.UUID,
    document_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Confirm all EXTRACTED fields for a shipment (or just one document within it).
    Skips fields already confirmed or corrected.
    Returns {confirmed: N}.
    """
    query = select(ExtractedField).where(
        ExtractedField.shipment_id == shipment_id,
        ExtractedField.status == ExtractedFieldStatus.EXTRACTED,
    )
    if document_id:
        query = query.where(ExtractedField.document_id == document_id)

    result = await db.execute(query)
    fields = list(result.scalars())
    now = datetime.now(timezone.utc)
    for field in fields:
        field.status = ExtractedFieldStatus.CONFIRMED
        field.confirmed_at = now
        field.confirmed_by = current_user.id

    await db.commit()
    return {"confirmed": len(fields)}


@router.get("/shipments/{shipment_id}/field-mismatches", response_model=ShipmentMismatchOut)
async def get_shipment_field_mismatches(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Compare extracted field values AND product lines across all documents in a shipment.

    Returns:
    - mismatches: shipment-level fields that contradict across documents
      (currency, weights, HS code, invoice value, incoterm, dates, parties, ports)
    - product_mismatches: products matched by HS code or name that have
      differing quantity / unit price / currency / origin across documents

    severity=error → customs-critical discrepancy
    severity=warning → notable but not blocking
    """
    from app.modules.field_extraction.service import detect_product_mismatches, detect_shipment_mismatches

    raw_field = await detect_shipment_mismatches(shipment_id, db)
    raw_matched, raw_unmatched = await detect_product_mismatches(shipment_id, db)

    field_mismatches = [
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
        for m in raw_field
    ]

    product_mismatches = [
        ProductGroupMismatch(
            product_key=g["product_key"],
            hs_code=g["hs_code"],
            field_mismatches=[
                ProductFieldMismatch(
                    field_name=f["field_name"],
                    display_label=f["display_label"],
                    severity=f["severity"],
                    values=[
                        ProductMismatchValue(
                            document_id=v["document_id"],
                            product_id=v["product_id"],
                            product_name=v["product_name"],
                            value=v["value"],
                        )
                        for v in f["values"]
                    ],
                )
                for f in g["field_mismatches"]
            ],
        )
        for g in raw_matched
    ]

    unmatched_products = [
        UnmatchedProduct(
            document_id=u["document_id"],
            product_id=u["product_id"],
            product_name=u["product_name"],
            hs_code=u["hs_code"],
            quantity=u["quantity"],
            unit_price=u["unit_price"],
            currency=u["currency"],
            missing_in=u["missing_in"],
        )
        for u in raw_unmatched
    ]

    return ShipmentMismatchOut(
        shipment_id=shipment_id,
        mismatches=field_mismatches,
        product_mismatches=product_mismatches,
        unmatched_products=unmatched_products,
    )


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
