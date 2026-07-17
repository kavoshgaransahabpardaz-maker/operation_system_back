"""
Shipment identification — runs synchronously inside Celery workers.
Extracts reference numbers via regex + OpenAI, matches/creates shipments.
"""
import json
import re
import uuid
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.document_classification.models import ClassificationResult, DocumentType
from app.modules.document_storage.models import Document, DocumentStatus
from app.modules.mismatch.fuzzy import names_match
from app.modules.ocr_processing.models import OcrResult
from app.modules.shipment_identification.models import (
    ReferenceType,
    Shipment,
    ShipmentDocument,
    ShipmentReference,
    ShipmentStatus,
)

_PARTY_FIELDS = {"party_shipper", "party_consignee"}
_DATE_FIELDS = {"invoice_date", "shipment_date"}
_PARTY_MATCH_THRESHOLD = 0.80
_DATE_WINDOW_DAYS = 5

# Common date formats tried in order when parsing extracted date fields
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y%m%d",
)


def _parse_date_safe(raw: str):
    """Try to parse raw string into a date object using common formats. Returns None on failure."""
    from datetime import date as date_type, datetime as dt_type
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt_type.strptime(raw, fmt).date()
        except ValueError:
            continue
    # Last attempt: ISO fromisoformat (Python 3.11 accepts many variants)
    try:
        return dt_type.fromisoformat(raw).date()
    except (ValueError, TypeError):
        return None

# Regex patterns for common reference formats
_PATTERNS: dict[ReferenceType, list[str]] = {
    ReferenceType.BL: [
        r"\bB/?L\s*(?:NO\.?|NUMBER)?[#:\s]*([A-Z0-9]{6,20})\b",
        r"\bBILL\s+OF\s+LADING[\s\S]*?(?:NO\.?|NUMBER|BL)?[#:\s]*([A-Z0-9]{6,20})\b",
    ],
    ReferenceType.AWB: [r"\bAWB[#:\s]*(\d{3}-\d{7,8})\b", r"\bAIR\s+WAYBILL[#:\s]*(\d{3}-\d{7,8})\b"],
    ReferenceType.INVOICE: [r"\bINVOICE\s+(?:NO|NUMBER|#)[.:\s]*([A-Z0-9\-/]{3,20})\b"],
    ReferenceType.PO: [r"\bPO[#:\s]*([A-Z0-9\-]{3,20})\b", r"\bPURCHASE\s+ORDER[#:\s]*([A-Z0-9\-]{3,20})\b"],
    ReferenceType.CONTAINER: [r"\b([A-Z]{4}\d{7})\b"],
}

_EXTRACTION_SYSTEM = """Extract shipment reference numbers from the document.
Return a JSON object with these optional keys (only include if found):
{"bl": "...", "awb": "...", "invoice": "...", "po": "...", "container": "...", "internal": "..."}
If none found, return {}."""


def _regex_extract(text: str) -> dict[ReferenceType, str]:
    found: dict[ReferenceType, str] = {}
    upper = text.upper()
    for ref_type, patterns in _PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, upper)
            if match:
                found[ref_type] = match.group(1)
                break
    return found


def _llm_extract(text: str) -> dict[ReferenceType, str]:
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    snippet = text[:4000]
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {"role": "user", "content": snippet},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = json.loads(response.choices[0].message.content)
    mapping = {"bl": ReferenceType.BL, "awb": ReferenceType.AWB, "invoice": ReferenceType.INVOICE,
               "po": ReferenceType.PO, "container": ReferenceType.CONTAINER, "internal": ReferenceType.INTERNAL}
    return {mapping[k]: v for k, v in raw.items() if k in mapping and v}


def identify_and_associate(db: Session, document_id: uuid.UUID) -> Shipment | None:
    doc: Document = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"Document {document_id} not found")

    # If the document was explicitly uploaded to an existing shipment, never override it.
    # The classification API pipeline (extract_fields_task) handles invoice-ref linking.
    if doc.shipment_id:
        return db.query(Shipment).filter(Shipment.id == doc.shipment_id).first()

    ocr: OcrResult = db.query(OcrResult).filter(OcrResult.document_id == document_id).first()
    if not ocr:
        doc.status = DocumentStatus.UNMATCHED
        db.commit()
        return None

    # Try regex first; fall back to LLM if nothing found
    refs = _regex_extract(ocr.raw_text)
    if not refs:
        refs = _llm_extract(ocr.raw_text)

    shipment = None

    if refs:
        # Find existing shipment by any matching reference
        for ref_type, ref_value in refs.items():
            existing_ref = db.query(ShipmentReference).filter(
                ShipmentReference.org_id == doc.org_id,
                ShipmentReference.ref_type == ref_type,
                ShipmentReference.ref_value == ref_value,
            ).first()
            if existing_ref:
                shipment = db.query(Shipment).filter(Shipment.id == existing_ref.shipment_id).first()
                break

        # Create new shipment if refs found but no reference match
        if not shipment:
            shipment = Shipment(org_id=doc.org_id, status=ShipmentStatus.ACTIVE)
            db.add(shipment)
            db.flush()

        # Add any new references to the shipment
        for ref_type, ref_value in refs.items():
            ref_exists = db.query(ShipmentReference).filter(
                ShipmentReference.shipment_id == shipment.id,
                ShipmentReference.ref_type == ref_type,
            ).first()
            if not ref_exists:
                db.add(ShipmentReference(
                    shipment_id=shipment.id,
                    org_id=doc.org_id,
                    ref_type=ref_type,
                    ref_value=ref_value,
                ))
    else:
        # No references found at all — try party+date fallback (sync wrapper)
        shipment = _fallback_match_by_party_and_date_sync(db, document_id, doc.org_id)
        if shipment is None:
            doc.status = DocumentStatus.UNMATCHED
            db.commit()
            return None

    # Associate document with shipment (idempotent)
    assoc_exists = db.query(ShipmentDocument).filter(
        ShipmentDocument.document_id == document_id
    ).first()
    if not assoc_exists:
        db.add(ShipmentDocument(shipment_id=shipment.id, document_id=document_id))

    doc.shipment_id = shipment.id
    doc.status = DocumentStatus.MATCHED
    db.commit()
    return shipment


def _fallback_match_by_party_and_date_sync(
    db: Session,
    document_id: uuid.UUID,
    org_id: uuid.UUID,
) -> Shipment | None:
    """
    Sync version of party+date fallback for use inside Celery tasks.

    1. Get extracted fields for this document.
    2. If no party fields available: return None (ambiguous → UNMATCHED).
    3. For each org shipment, fuzzy-match party names and check date window.
    4. Exactly one match → return it; zero or multiple → return None.
    """
    from app.modules.field_extraction.models import ExtractedField

    fields = db.query(ExtractedField).filter(ExtractedField.document_id == document_id).all()
    if not fields:
        return None

    field_map: dict[str, str] = {f.field_name: (f.value_normalized or f.value_raw) for f in fields}

    # Need at least one party field
    party_shipper = field_map.get("party_shipper")
    party_consignee = field_map.get("party_consignee")
    if not party_shipper and not party_consignee:
        return None

    # Collect document dates
    doc_dates = []
    for date_field in _DATE_FIELDS:
        raw = field_map.get(date_field)
        if raw:
            d = _parse_date_safe(raw)
            if d is not None:
                doc_dates.append(d)

    org_shipments = db.query(Shipment).filter(Shipment.org_id == org_id).all()
    matched: list[Shipment] = []

    for shipment in org_shipments:
        # Get extracted fields for all documents in this shipment
        ship_docs = db.query(Document).filter(Document.shipment_id == shipment.id).all()
        ship_field_map: dict[str, list[str]] = {}
        for ship_doc in ship_docs:
            s_fields = db.query(ExtractedField).filter(ExtractedField.document_id == ship_doc.id).all()
            for sf in s_fields:
                ship_field_map.setdefault(sf.field_name, []).append(sf.value_normalized or sf.value_raw)

        # Check party match
        party_match = False
        for party_field in ("party_shipper", "party_consignee"):
            doc_val = field_map.get(party_field)
            if not doc_val:
                continue
            for ship_val in ship_field_map.get(party_field, []):
                if names_match(doc_val, ship_val, _PARTY_MATCH_THRESHOLD):
                    party_match = True
                    break
            if party_match:
                break

        if not party_match:
            continue

        # If no dates on either side, party match alone is enough
        if not doc_dates:
            matched.append(shipment)
            continue

        # Check date window
        ship_dates = []
        for date_field in _DATE_FIELDS:
            for raw in ship_field_map.get(date_field, []):
                d = _parse_date_safe(raw)
                if d is not None:
                    ship_dates.append(d)

        if not ship_dates:
            # No dates on shipment side — party match alone counts
            matched.append(shipment)
            continue

        date_ok = any(
            abs((d - s).days) <= _DATE_WINDOW_DAYS
            for d in doc_dates
            for s in ship_dates
        )
        if date_ok:
            matched.append(shipment)

    if len(matched) == 1:
        return matched[0]

    # Zero or multiple matches → ambiguous; create a warning flag (best-effort, sync)
    if len(matched) > 1:
        _create_ambiguous_match_flag_sync(db, document_id, org_id)

    return None


def _create_ambiguous_match_flag_sync(
    db: Session,
    document_id: uuid.UUID,
    org_id: uuid.UUID,
) -> None:
    """Create a warning flag indicating ambiguous shipment match (sync, best-effort)."""
    try:
        from app.modules.flags.models import Flag, FlagSeverity, FlagStatus, FlagType
        # Flags require a shipment_id (non-nullable FK); we can't create one without a shipment.
        # Instead, mark document NEEDS_REVIEW — the flag will be raised post-matching.
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.status = DocumentStatus.NEEDS_REVIEW
        db.commit()
    except Exception:
        pass  # best-effort; do not block the pipeline


def reassociate_document(
    db: Session, document_id: uuid.UUID, new_shipment_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    assoc = db.query(ShipmentDocument).filter(ShipmentDocument.document_id == document_id).first()
    if assoc:
        assoc.shipment_id = new_shipment_id
        assoc.associated_by = user_id
    else:
        db.add(ShipmentDocument(
            shipment_id=new_shipment_id, document_id=document_id, associated_by=user_id
        ))

    doc: Document = db.query(Document).filter(Document.id == document_id).first()
    if doc:
        doc.shipment_id = new_shipment_id
        doc.status = DocumentStatus.MATCHED
    db.commit()


async def compute_shipment_status(shipment_id: uuid.UUID, db: AsyncSession) -> str:
    """
    Compute correct shipment status based on current pipeline state.

    Rules (in priority order):
    1. Any document still in ocr_pending/ocr_processing  → 'active'  (still ingesting)
    2. Any open flag with severity=critical or warning    → 'on_hold' (flags_open)
    3. Any extracted field status='extracted' + conf<0.70 → 'on_hold' (needs_review)
    4. Otherwise                                          → 'active'  (clear)

    Note: 'complete' is set only manually by the user — never returned here.
    """
    from app.modules.document_storage.models import DocumentStatus as DS
    from app.modules.field_extraction.models import ExtractedField, ExtractedFieldStatus
    from app.modules.flags.models import Flag, FlagSeverity, FlagStatus

    # 1. Any document still ingesting?
    ingesting_result = await db.execute(
        select(Document).where(
            Document.shipment_id == shipment_id,
            Document.status.in_([DS.OCR_PENDING, DS.OCR_PROCESSING]),
        ).limit(1)
    )
    if ingesting_result.scalar_one_or_none():
        return "active"

    # 2. Any open critical/warning flag?
    flag_result = await db.execute(
        select(Flag).where(
            Flag.shipment_id == shipment_id,
            Flag.status == FlagStatus.OPEN,
            Flag.severity.in_([FlagSeverity.CRITICAL, FlagSeverity.WARNING]),
        ).limit(1)
    )
    if flag_result.scalar_one_or_none():
        return "on_hold"

    # 3. Any low-confidence unreviewed field?
    field_result = await db.execute(
        select(ExtractedField).where(
            ExtractedField.shipment_id == shipment_id,
            ExtractedField.status == ExtractedFieldStatus.EXTRACTED,
            ExtractedField.confidence < 0.70,
        ).limit(1)
    )
    if field_result.scalar_one_or_none():
        return "on_hold"

    return "active"


async def auto_update_shipment_status(shipment_id: uuid.UUID, db: AsyncSession) -> None:
    """Recompute shipment status and persist if changed. Log to activity_log."""
    from app.models.activity_log import ActivityAction, ActivityLog

    ship_result = await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    shipment = ship_result.scalar_one_or_none()
    if not shipment:
        return

    # Never overwrite a manually-set 'complete'
    if shipment.status == ShipmentStatus.COMPLETE:
        return

    new_status_str = await compute_shipment_status(shipment_id, db)
    new_status = ShipmentStatus(new_status_str)

    if shipment.status != new_status:
        old_status = shipment.status
        shipment.status = new_status
        log_entry = ActivityLog(
            org_id=shipment.org_id,
            shipment_id=shipment_id,
            action=ActivityAction.SHIPMENT_STATUS_UPDATED,
            details={"old_status": old_status.value, "new_status": new_status.value},
        )
        db.add(log_entry)
        await db.commit()


async def update_shipment_status(
    db: AsyncSession, org_id: uuid.UUID, shipment_id: uuid.UUID, new_status: ShipmentStatus
) -> Shipment:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Shipment)
        .where(Shipment.id == shipment_id, Shipment.org_id == org_id)
        .options(selectinload(Shipment.references))
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    shipment.status = new_status
    await db.commit()
    # Re-query with selectinload so references are available for serialization
    result2 = await db.execute(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(selectinload(Shipment.references))
    )
    return result2.scalar_one()


async def delete_shipment(db: AsyncSession, org_id: uuid.UUID, shipment_id: uuid.UUID) -> None:
    from sqlalchemy import delete as sql_delete, update as sql_update
    from app.modules.flags.models import Flag, FlagResolution
    from app.modules.field_extraction.models import ExtractedField
    from app.modules.intel.models import IntelMatch
    from app.modules.classification_api.models import DocumentProduct

    result = await db.execute(
        select(Shipment).where(Shipment.id == shipment_id, Shipment.org_id == org_id)
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")

    # Unlink documents (clear their shipment_id, keep the documents themselves)
    await db.execute(
        sql_update(Document)
        .where(Document.shipment_id == shipment_id)
        .values(shipment_id=None)
    )
    # Nullify shipment_id on extracted fields
    await db.execute(
        sql_update(ExtractedField)
        .where(ExtractedField.shipment_id == shipment_id)
        .values(shipment_id=None)
    )
    # Nullify shipment_id on document products (FK to shipments, no cascade)
    await db.execute(
        sql_update(DocumentProduct)
        .where(DocumentProduct.shipment_id == shipment_id)
        .values(shipment_id=None)
    )
    # Delete flag resolutions first (FK to flags)
    flag_ids_result = await db.execute(
        select(Flag.id).where(Flag.shipment_id == shipment_id)
    )
    flag_ids = [r[0] for r in flag_ids_result.all()]
    if flag_ids:
        await db.execute(sql_delete(FlagResolution).where(FlagResolution.flag_id.in_(flag_ids)))
    await db.execute(sql_delete(Flag).where(Flag.shipment_id == shipment_id))
    # Delete intel matches
    await db.execute(sql_delete(IntelMatch).where(IntelMatch.shipment_id == shipment_id))
    # Delete shipment join tables
    await db.execute(sql_delete(ShipmentDocument).where(ShipmentDocument.shipment_id == shipment_id))
    await db.execute(sql_delete(ShipmentReference).where(ShipmentReference.shipment_id == shipment_id))
    await db.execute(sql_delete(Shipment).where(Shipment.id == shipment_id))
    await db.commit()
