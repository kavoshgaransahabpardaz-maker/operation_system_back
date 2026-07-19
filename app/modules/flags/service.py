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
from app.modules.flags.models import Flag, FlagResolution, FlagSeverity, FlagStatus, FlagType, ResolutionDecision
from app.modules.mismatch.engine import compare_shipment_fields
from app.modules.org_settings.service import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-doc-type required field definitions
# ---------------------------------------------------------------------------

#: Human-readable labels for field names used in flag titles.
FIELD_NAME_LABELS: dict[str, str] = {
    "party_shipper": "Shipper",
    "party_consignee": "Consignee",
    "invoice_value": "Invoice Value",
    "currency": "Currency",
    "hs_code": "HS Code",
    "stated_origin": "Country of Origin",
    "incoterm": "Incoterm",
    "invoice_date": "Invoice Date",
    "gross_weight": "Gross Weight",
    "net_weight": "Net Weight",
    "quantity": "Quantity",
    "reference": "Reference Number",
    "shipment_date": "Shipment Date",
}

REQUIRED_FIELDS_BY_DOC_TYPE: dict[str, list[str]] = {
    "COMMERCIAL_INVOICE": [
        "party_shipper", "party_consignee", "invoice_value", "currency",
        "hs_code", "stated_origin", "incoterm", "invoice_date",
    ],
    "BILL_OF_LADING": [
        "party_shipper", "party_consignee", "gross_weight", "stated_origin", "reference",
    ],
    "PACKING_LIST": [
        "party_shipper", "party_consignee", "gross_weight", "net_weight", "quantity",
    ],
    "AIR_WAYBILL": [
        "party_shipper", "party_consignee", "gross_weight", "stated_origin", "reference",
    ],
    "CERTIFICATE_OF_ORIGIN": [
        "party_shipper", "stated_origin",
    ],
    # All other doc types have no mandatory fields
}

# ---------------------------------------------------------------------------
# Expected-document profiles
# ---------------------------------------------------------------------------

DOC_TYPE_LABELS: dict[str, str] = {
    "COMMERCIAL_INVOICE": "Commercial Invoice",
    "PACKING_LIST": "Packing List",
    "BILL_OF_LADING": "Bill of Lading",
    "AIR_WAYBILL": "Air Waybill",
    "CERTIFICATE_OF_ORIGIN": "Certificate of Origin",
    "CUSTOMS_DECLARATION": "Customs Declaration",
    "INSURANCE_CERTIFICATE": "Insurance Certificate",
    "PURCHASE_ORDER": "Purchase Order",
    "DELIVERY_ORDER": "Delivery Order",
    "MILL_CERTIFICATE": "Mill Certificate",
    "SUPPLIERS_DECLARATION": "Supplier's Declaration",
    "CMR": "CMR Consignment Note",
}

SHIPMENT_PROFILES: dict[str, list[str]] = {
    "steel_import": [
        "COMMERCIAL_INVOICE",
        "PACKING_LIST",
        "BILL_OF_LADING",
        "CERTIFICATE_OF_ORIGIN",
    ],
    "default": [
        "COMMERCIAL_INVOICE",
        "PACKING_LIST",
    ],
}


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


async def create_missing_field_flags(
    document_id: uuid.UUID,
    doc_type: str,
    shipment_id: uuid.UUID,
    org_id: uuid.UUID | None,
    db: AsyncSession,
) -> None:
    """
    For a classified document, raise a warning flag for each required field that was
    not found among the extracted fields.
    """
    required = REQUIRED_FIELDS_BY_DOC_TYPE.get(doc_type.upper(), [])
    if not required:
        return

    fields_result = await db.execute(
        select(ExtractedField).where(ExtractedField.document_id == document_id)
    )
    extracted_names = {f.field_name for f in fields_result.scalars()}

    for field in required:
        if field in extracted_names:
            continue

        label = FIELD_NAME_LABELS.get(field, field)
        doc_label = doc_type.replace("_", " ").title()

        # Deduplication
        dup = await db.execute(
            select(Flag).where(
                Flag.shipment_id == shipment_id,
                Flag.flag_type == FlagType.MISSING_FIELD,
                Flag.title == f"Missing field: {label}",
                Flag.status == FlagStatus.OPEN,
            )
        )
        if dup.scalar_one_or_none():
            continue

        flag = Flag(
            shipment_id=shipment_id,
            org_id=org_id,
            flag_type=FlagType.MISSING_FIELD,
            severity=FlagSeverity.WARNING,
            title=f"Missing field: {label}",
            description=f"Required field '{label}' not found in {doc_label}.",
            status=FlagStatus.OPEN,
        )
        db.add(flag)

    await db.commit()


async def create_missing_document_flags(
    shipment_id: uuid.UUID,
    profile: str,
    org_id: uuid.UUID | None,
    db: AsyncSession,
) -> None:
    """
    Compare the doc types present on a shipment against the expected profile and raise
    a warning flag for each missing doc type.
    """
    from app.modules.document_classification.models import ClassificationResult
    from app.modules.document_storage.models import Document

    expected = SHIPMENT_PROFILES.get(profile, SHIPMENT_PROFILES["default"])

    docs_result = await db.execute(
        select(Document).where(Document.shipment_id == shipment_id)
    )
    doc_ids = [d.id for d in docs_result.scalars()]

    present_types: set[str] = set()
    if doc_ids:
        cls_result = await db.execute(
            select(ClassificationResult).where(
                ClassificationResult.document_id.in_(doc_ids)
            )
        )
        for cr in cls_result.scalars():
            present_types.add(cr.doc_type.value.upper())

    for expected_type in expected:
        label = DOC_TYPE_LABELS.get(expected_type.upper(), expected_type)

        if expected_type.upper() in present_types:
            # Auto-resolve any open "Missing document" flag for this type
            open_flags = await db.execute(
                select(Flag).where(
                    Flag.shipment_id == shipment_id,
                    Flag.flag_type == FlagType.MISSING_DOCUMENT,
                    Flag.title == f"Missing document: {label}",
                    Flag.status == FlagStatus.OPEN,
                )
            )
            for flag in open_flags.scalars():
                flag.status = FlagStatus.RESOLVED
            continue

        # Deduplication — skip if open flag already exists
        dup = await db.execute(
            select(Flag).where(
                Flag.shipment_id == shipment_id,
                Flag.flag_type == FlagType.MISSING_DOCUMENT,
                Flag.title == f"Missing document: {label}",
                Flag.status == FlagStatus.OPEN,
            )
        )
        if dup.scalar_one_or_none():
            continue

        flag = Flag(
            shipment_id=shipment_id,
            org_id=org_id,
            flag_type=FlagType.MISSING_DOCUMENT,
            severity=FlagSeverity.WARNING,
            title=f"Missing document: {label}",
            description=f"Expected document type '{label}' not found in shipment.",
            status=FlagStatus.OPEN,
        )
        db.add(flag)

    await db.commit()


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

    # Recompute shipment status after flag resolution
    if flag.shipment_id:
        try:
            from app.modules.shipment_identification.service import auto_update_shipment_status
            await auto_update_shipment_status(flag.shipment_id, db)
        except Exception:
            pass  # best-effort; do not block flag response

    return flag
