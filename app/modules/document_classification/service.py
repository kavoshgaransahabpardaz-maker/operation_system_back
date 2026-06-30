"""
Document classification — runs synchronously inside Celery workers.
Uses OpenAI to classify document type from OCR text.
"""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.document_classification.models import ClassificationResult, DocumentType
from app.modules.document_storage.models import Document, DocumentStatus
from app.modules.ocr_processing.models import OcrResult

CONFIDENCE_REVIEW_THRESHOLD = 0.70

_SYSTEM_PROMPT = """You are a customs brokerage expert. Classify the document into exactly one of these types:
- commercial_invoice
- packing_list
- bill_of_lading
- air_waybill
- certificate_of_origin
- insurance_certificate
- customs_declaration
- purchase_order
- delivery_order
- other

Respond ONLY with a JSON object in this exact format:
{"doc_type": "<type>", "confidence": <0.0-1.0>}"""


def classify_document(db: Session, document_id: uuid.UUID) -> ClassificationResult:
    existing = db.query(ClassificationResult).filter(
        ClassificationResult.document_id == document_id,
        ClassificationResult.is_manual_override == False,
    ).first()
    if existing:
        return existing

    ocr: OcrResult = db.query(OcrResult).filter(OcrResult.document_id == document_id).first()
    if not ocr:
        raise ValueError(f"No OCR result for document {document_id}")

    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    text_snippet = ocr.raw_text[:4000]  # keep within token budget
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Document text:\n{text_snippet}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw = json.loads(response.choices[0].message.content)
    doc_type_str = raw.get("doc_type", "other")
    confidence = float(raw.get("confidence", 0.5))

    try:
        doc_type = DocumentType(doc_type_str)
    except ValueError:
        doc_type = DocumentType.OTHER

    result = ClassificationResult(
        document_id=document_id,
        doc_type=doc_type,
        confidence=confidence,
        is_manual_override=False,
    )
    db.add(result)

    doc: Document = db.query(Document).filter(Document.id == document_id).first()
    if doc:
        if confidence < CONFIDENCE_REVIEW_THRESHOLD:
            doc.status = DocumentStatus.NEEDS_REVIEW
        else:
            doc.status = DocumentStatus.CLASSIFIED
    db.commit()
    db.refresh(result)
    return result


def override_classification(
    db: Session, document_id: uuid.UUID, doc_type: DocumentType, user_id: uuid.UUID
) -> ClassificationResult:
    existing = db.query(ClassificationResult).filter(ClassificationResult.document_id == document_id).first()
    if existing:
        existing.doc_type = doc_type
        existing.confidence = 1.0
        existing.is_manual_override = True
        existing.classified_by = user_id
        existing.classified_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    result = ClassificationResult(
        document_id=document_id,
        doc_type=doc_type,
        confidence=1.0,
        is_manual_override=True,
        classified_by=user_id,
    )
    db.add(result)

    doc: Document = db.query(Document).filter(Document.id == document_id).first()
    if doc:
        doc.status = DocumentStatus.CLASSIFIED
    db.commit()
    db.refresh(result)
    return result


async def override_classification_async(
    db: AsyncSession, document_id: uuid.UUID, doc_type: DocumentType, user_id: uuid.UUID
) -> ClassificationResult:
    existing_result = await db.execute(
        select(ClassificationResult).where(ClassificationResult.document_id == document_id)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        existing.doc_type = doc_type
        existing.confidence = 1.0
        existing.is_manual_override = True
        existing.classified_by = user_id
        existing.classified_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return existing

    cr = ClassificationResult(
        document_id=document_id,
        doc_type=doc_type,
        confidence=1.0,
        is_manual_override=True,
        classified_by=user_id,
    )
    db.add(cr)

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if doc:
        doc.status = DocumentStatus.CLASSIFIED
    await db.commit()
    await db.refresh(cr)
    return cr
