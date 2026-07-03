"""
Field extraction service.
Calls OpenAI to extract structured fields from document OCR text,
validates and normalizes each field, then bulk-inserts ExtractedField rows.
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.document_classification.models import ClassificationResult
from app.modules.document_storage.models import Document
from app.modules.field_extraction.models import ExtractedField, ExtractedFieldStatus, FieldType
from app.modules.field_extraction.normalizers import normalize_field
from app.modules.field_extraction.schemas import FieldName, LLMFieldsResponse
from app.modules.field_extraction.validators import get_validator
from app.modules.ocr_processing.models import OcrResult

logger = logging.getLogger(__name__)

# Fields expected per document type
DOC_TYPE_FIELDS: dict[str, list[FieldName]] = {
    "commercial_invoice": [
        FieldName.PARTY_SHIPPER,
        FieldName.PARTY_CONSIGNEE,
        FieldName.INVOICE_VALUE,
        FieldName.CURRENCY,
        FieldName.GROSS_WEIGHT,
        FieldName.NET_WEIGHT,
        FieldName.QUANTITY,
        FieldName.HS_CODE,
        FieldName.STATED_ORIGIN,
        FieldName.INCOTERM,
        FieldName.INVOICE_DATE,
        FieldName.REFERENCE,
    ],
    "bill_of_lading": [
        FieldName.PARTY_SHIPPER,
        FieldName.PARTY_CONSIGNEE,
        FieldName.GROSS_WEIGHT,
        FieldName.QUANTITY,
        FieldName.STATED_ORIGIN,
        FieldName.INCOTERM,
        FieldName.SHIPMENT_DATE,
        FieldName.REFERENCE,
    ],
    "packing_list": [
        FieldName.PARTY_SHIPPER,
        FieldName.PARTY_CONSIGNEE,
        FieldName.GROSS_WEIGHT,
        FieldName.NET_WEIGHT,
        FieldName.QUANTITY,
        FieldName.REFERENCE,
    ],
    "air_waybill": [
        FieldName.PARTY_SHIPPER,
        FieldName.PARTY_CONSIGNEE,
        FieldName.GROSS_WEIGHT,
        FieldName.QUANTITY,
        FieldName.STATED_ORIGIN,
        FieldName.SHIPMENT_DATE,
        FieldName.REFERENCE,
    ],
}
_DEFAULT_FIELDS = [FieldName.REFERENCE]

# Field-type mapping for metadata
_FIELD_TYPE_MAP: dict[FieldName, FieldType] = {
    FieldName.INVOICE_VALUE: FieldType.DECIMAL,
    FieldName.GROSS_WEIGHT: FieldType.DECIMAL,
    FieldName.NET_WEIGHT: FieldType.DECIMAL,
    FieldName.QUANTITY: FieldType.DECIMAL,
    FieldName.CURRENCY: FieldType.ISO_CODE,
    FieldName.STATED_ORIGIN: FieldType.ISO_CODE,
    FieldName.INCOTERM: FieldType.ISO_CODE,
    FieldName.INVOICE_DATE: FieldType.DATE,
    FieldName.SHIPMENT_DATE: FieldType.DATE,
}

_CONFIDENCE_PENALTY = 0.2


def _build_prompt(doc_type: str, field_names: list[FieldName], ocr_text: str) -> str:
    field_list = ", ".join(fn.value for fn in field_names)
    return (
        f"You are a customs document parser. Extract the following fields from the document text below.\n"
        f"Document type: {doc_type}\n"
        f"Fields to extract: {field_list}\n\n"
        f"Return a JSON object with a single key 'fields' containing an array of objects.\n"
        f"Each object must have:\n"
        f"  - field_name: one of [{field_list}]\n"
        f"  - value_raw: the exact text as it appears in the document\n"
        f"  - confidence: float 0.0-1.0\n"
        f"  - page_number: integer or null\n\n"
        f"Only include fields that are actually present in the document.\n\n"
        f"Document text:\n{ocr_text[:6000]}"
    )


async def extract_fields(document_id: uuid.UUID, db: AsyncSession) -> list[ExtractedField]:
    # 1. Load document
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise ValueError(f"Document {document_id} not found")

    # 2. Load OCR result
    ocr_result = await db.execute(select(OcrResult).where(OcrResult.document_id == document_id))
    ocr = ocr_result.scalar_one_or_none()
    if not ocr:
        raise ValueError(f"No OCR result for document {document_id}")

    # 3. Load classification
    cls_result = await db.execute(
        select(ClassificationResult).where(ClassificationResult.document_id == document_id)
    )
    classification = cls_result.scalar_one_or_none()

    doc_type = classification.doc_type.value if classification else "other"
    field_names = DOC_TYPE_FIELDS.get(doc_type, _DEFAULT_FIELDS)

    if not field_names:
        return []

    # 4. Call OpenAI
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = _build_prompt(doc_type, field_names, ocr.raw_text)
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a customs document field extractor. Always respond with valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content

    # 5. Parse through Pydantic — malformed output raises before any DB write
    try:
        parsed = LLMFieldsResponse.model_validate(json.loads(raw_content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"LLM returned invalid field extraction JSON: {exc}") from exc

    # 6. Validate + normalize each field, build ORM rows
    inserted: list[ExtractedField] = []
    for item in parsed.fields:
        confidence = float(item.confidence)
        confidence = max(0.0, min(1.0, confidence))

        validator = get_validator(item.field_name)
        if validator is not None:
            is_valid, reason = validator(item.value_raw)
            if not is_valid:
                logger.debug(
                    "Validation failed for field %s value '%s': %s",
                    item.field_name, item.value_raw, reason,
                )
                confidence = max(0.0, confidence - _CONFIDENCE_PENALTY)

        value_normalized = normalize_field(item.field_name, item.value_raw)

        try:
            fn_enum = FieldName(item.field_name)
            ftype = _FIELD_TYPE_MAP.get(fn_enum, FieldType.STRING).value
        except ValueError:
            ftype = FieldType.STRING.value

        ef = ExtractedField(
            document_id=document_id,
            shipment_id=doc.shipment_id,
            org_id=doc.org_id,
            field_name=item.field_name,
            value_raw=item.value_raw,
            value_normalized=value_normalized,
            field_type=ftype,
            confidence=confidence,
            page_number=item.page_number,
            status=ExtractedFieldStatus.EXTRACTED,
        )
        db.add(ef)
        inserted.append(ef)

    await db.commit()
    for ef in inserted:
        await db.refresh(ef)

    logger.info("Extracted %d fields for document %s", len(inserted), document_id)
    return inserted
