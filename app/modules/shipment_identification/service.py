"""
Shipment identification — runs synchronously inside Celery workers.
Extracts reference numbers via regex + OpenAI, matches/creates shipments.
"""
import json
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.document_classification.models import ClassificationResult, DocumentType
from app.modules.document_storage.models import Document, DocumentStatus
from app.modules.ocr_processing.models import OcrResult
from app.modules.shipment_identification.models import (
    ReferenceType,
    Shipment,
    ShipmentDocument,
    ShipmentReference,
    ShipmentStatus,
)

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

    ocr: OcrResult = db.query(OcrResult).filter(OcrResult.document_id == document_id).first()
    if not ocr:
        doc.status = DocumentStatus.UNMATCHED
        db.commit()
        return None

    # Try regex first; fall back to LLM if nothing found
    refs = _regex_extract(ocr.raw_text)
    if not refs:
        refs = _llm_extract(ocr.raw_text)

    if not refs:
        doc.status = DocumentStatus.UNMATCHED
        db.commit()
        return None

    # Find existing shipment by any matching reference
    shipment = None
    for ref_type, ref_value in refs.items():
        existing_ref = db.query(ShipmentReference).filter(
            ShipmentReference.org_id == doc.org_id,
            ShipmentReference.ref_type == ref_type,
            ShipmentReference.ref_value == ref_value,
        ).first()
        if existing_ref:
            shipment = db.query(Shipment).filter(Shipment.id == existing_ref.shipment_id).first()
            break

    # Create new shipment if no match
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
