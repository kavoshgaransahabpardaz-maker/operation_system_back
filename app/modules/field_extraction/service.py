"""
Field extraction service.
Calls OpenAI to extract structured fields from document OCR text,
validates and normalizes each field, then bulk-inserts ExtractedField rows.

Universal extraction: every document is scanned for all CI+PL fields defined
in UNIVERSAL_FIELDS. The LLM only returns fields actually present in the text,
so non-relevant fields are naturally omitted.
"""
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation

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

# ── Universal fields ─────────────────────────────────────────────────────────
# Attempted for every uploaded document regardless of type.
# The LLM only returns fields it actually finds in the text.
UNIVERSAL_FIELDS: list[FieldName] = [
    # Parties
    FieldName.PARTY_SHIPPER,
    FieldName.VAT_NUMBER_SELLER,
    FieldName.REX_NUMBER_SELLER,
    FieldName.PARTY_CONSIGNEE,
    FieldName.VAT_NUMBER_BUYER,
    FieldName.REX_NUMBER_BUYER,
    FieldName.EORI_NUMBER,
    # Financials
    FieldName.INVOICE_VALUE,
    FieldName.VAT_VALUE,
    FieldName.FREIGHT_VALUE,
    FieldName.INSURANCE_VALUE,
    FieldName.CURRENCY,
    # Weights & quantities
    FieldName.GROSS_WEIGHT,
    FieldName.NET_WEIGHT,
    FieldName.QUANTITY,
    FieldName.TOTAL_PACKAGES,
    # Product
    FieldName.HS_CODE,
    FieldName.COMMODITY_DESCRIPTION,
    FieldName.LOT_NUMBER,
    FieldName.PRODUCT_REGISTRATION_NUMBER,
    FieldName.PRODUCT_SERIAL_NUMBER,
    # Trade terms & compliance
    FieldName.STATED_ORIGIN,
    FieldName.DESTINATION_COUNTRY,
    FieldName.PLACE_OF_LOADING,
    FieldName.INCOTERM,
    FieldName.PREFERENTIAL_DUTY,
    # Dates
    FieldName.INVOICE_DATE,
    FieldName.DUE_DATE,
    FieldName.SHIPMENT_DATE,
    FieldName.EXPIRY_DATE,
    # Identifiers
    FieldName.REFERENCE,
    FieldName.LOCAL_REFERENCE,
    FieldName.POINT_OF_ENTRY,
]

# Fields checked for cross-document consistency within a shipment
MISMATCH_CHECK_FIELDS: set[str] = {
    # Identifiers
    FieldName.REFERENCE.value,           # invoice number must match across CI and PL
    FieldName.INCOTERM.value,
    # Financials (total-level, not per-product — per-product was removed from ExtractedField)
    FieldName.INVOICE_VALUE.value,
    FieldName.FREIGHT_VALUE.value,
    FieldName.INSURANCE_VALUE.value,
    FieldName.CURRENCY.value,
    # Weights & Measures
    FieldName.GROSS_WEIGHT.value,
    FieldName.NET_WEIGHT.value,
    # Geography
    FieldName.STATED_ORIGIN.value,
    FieldName.DESTINATION_COUNTRY.value,
    FieldName.PLACE_OF_LOADING.value,
    FieldName.PORT_OF_DISCHARGE.value,
    # Entities
    FieldName.PARTY_SHIPPER.value,
    FieldName.PARTY_CONSIGNEE.value,
    FieldName.VAT_NUMBER_SELLER.value,
    FieldName.VAT_NUMBER_BUYER.value,
    FieldName.EORI_NUMBER.value,
    # Dates
    FieldName.INVOICE_DATE.value,
    # HS_CODE omitted — compared at product level via DocumentProduct.existing_hs_code
}

# These mismatches are blocking / high-severity
MISMATCH_CRITICAL_FIELDS: set[str] = {
    FieldName.REFERENCE.value,           # invoice number cross-doc mismatch is critical
    FieldName.CURRENCY.value,
    FieldName.GROSS_WEIGHT.value,
    FieldName.NET_WEIGHT.value,
    FieldName.STATED_ORIGIN.value,
    FieldName.INVOICE_DATE.value,
    FieldName.EORI_NUMBER.value,
}

# Field-type mapping for metadata
_FIELD_TYPE_MAP: dict[FieldName, FieldType] = {
    FieldName.INVOICE_VALUE: FieldType.DECIMAL,
    FieldName.VAT_VALUE: FieldType.DECIMAL,
    FieldName.FREIGHT_VALUE: FieldType.DECIMAL,
    FieldName.INSURANCE_VALUE: FieldType.DECIMAL,
    FieldName.GROSS_WEIGHT: FieldType.DECIMAL,
    FieldName.NET_WEIGHT: FieldType.DECIMAL,
    FieldName.QUANTITY: FieldType.DECIMAL,
    FieldName.TOTAL_PACKAGES: FieldType.DECIMAL,
    FieldName.CURRENCY: FieldType.ISO_CODE,
    FieldName.STATED_ORIGIN: FieldType.ISO_CODE,
    FieldName.DESTINATION_COUNTRY: FieldType.ISO_CODE,
    FieldName.INCOTERM: FieldType.ISO_CODE,
    FieldName.INVOICE_DATE: FieldType.DATE,
    FieldName.DUE_DATE: FieldType.DATE,
    FieldName.SHIPMENT_DATE: FieldType.DATE,
    FieldName.EXPIRY_DATE: FieldType.DATE,
}

_DECIMAL_FIELD_NAMES: set[str] = {
    fn.value for fn, ft in _FIELD_TYPE_MAP.items() if ft == FieldType.DECIMAL
}

# Per-doc-type extraction notes injected into the LLM prompt
_DOC_TYPE_NOTES: dict[str, str] = {
    "commercial_invoice": (
        "DOCUMENT-SPECIFIC RULES (Commercial Invoice):\n"
        "- party_shipper: full seller name + address as one string.\n"
        "- party_consignee: full buyer name + address as one string.\n"
        "- vat_number_seller / vat_number_buyer: VAT registration number. "
        "EU formats vary: Bulgaria uses EIK (9-digit), Germany DE+9 digits, FR+11 chars, etc. "
        "Look for labels: 'VAT No', 'TVA', 'USt-IdNr', 'EIK', 'ДДС номер'.\n"
        "- rex_number_seller / rex_number_buyer: look for 'REX' followed by country code + digits, "
        "e.g. 'REX BG123456789'.\n"
        "- eori_number: 2-letter country code + up to 15 alphanumeric chars, e.g. 'GB123456789000'.\n"
        "- preferential_duty: if the document contains a self-certification statement or origin "
        "declaration (phrases like 'preferential origin', 'origin declaration', "
        "'The exporter of the products covered by this document declares...'), "
        "extract the full statement and set confidence high.\n"
        "- currency: if two currencies appear, return the currency of the DESTINATION country "
        "(e.g. for imports to UK prioritise GBP over EUR).\n"
        "- invoice_value: total value in the identified currency (exclude VAT).\n"
        "- vat_value: the VAT/tax amount separately.\n"
        "- due_date: payment due date, distinct from invoice_date.\n"
    ),
    "packing_list": (
        "DOCUMENT-SPECIFIC RULES (Packing List):\n"
        "- party_shipper is the CONSIGNOR (sender); party_consignee is the CONSIGNEE (receiver).\n"
        "- reference: include BOTH the packing list number AND the invoice number if present "
        "(semicolon-separated); this links the packing list to the commercial invoice.\n"
        "- lot_number: batch or lot number for the goods.\n"
        "- product_registration_number: regulatory registration number if shown.\n"
        "- product_serial_number: serial number of the goods.\n"
        "- expiry_date: expiration / best-before date.\n"
        "- total_packages: total count of packages/boxes/pallets.\n"
        "- freight_value / insurance_value: extract if shown as separate line items.\n"
    ),
}

_CONFIDENCE_PENALTY = 0.2


def _build_prompt(doc_type: str, ocr_text: str) -> str:
    field_list = ", ".join(fn.value for fn in UNIVERSAL_FIELDS)
    doc_notes = _DOC_TYPE_NOTES.get(doc_type, "")
    return (
        "You are a specialist customs document parser.\n"
        "Extract structured data from the document text below.\n"
        f"Document type: {doc_type}\n\n"
        "UNIVERSAL EXTRACTION RULES:\n"
        "- Scan for ANY of the following fields, regardless of document type.\n"
        "- Only include fields that are ACTUALLY PRESENT in the document. Do not fabricate.\n"
        "- party_shipper: full seller/consignor name + address as one string.\n"
        "- party_consignee: full buyer/consignee name + address as one string.\n"
        "- For dates, extract exactly as shown (normalisation happens server-side).\n"
        "- For weights/quantities, include the unit in value_raw (e.g. '830.0 kg').\n"
        "- For hs_code: commodity/tariff code (6-10 digits, may contain dots or spaces).\n"
        "- For eori_number: 2-letter country code + up to 15 alphanumeric chars.\n"
        f"\n{doc_notes}"
        f"\nFields to extract: {field_list}\n\n"
        "Return a JSON object with a single key 'fields' containing an array of objects.\n"
        "Each object must have:\n"
        "  - field_name: one of the fields listed above\n"
        "  - value_raw: the exact text as it appears in the document\n"
        "  - confidence: float 0.0-1.0\n"
        "  - page_number: integer or null\n\n"
        f"Document text:\n{ocr_text[:8000]}"
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

    # 3. Load classification (for doc-type-specific prompt notes)
    cls_result = await db.execute(
        select(ClassificationResult).where(ClassificationResult.document_id == document_id)
    )
    classification = cls_result.scalar_one_or_none()
    doc_type = classification.doc_type.value if classification else "other"

    # 4. Call OpenAI with universal field set
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = _build_prompt(doc_type, ocr.raw_text)
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
        confidence = max(0.0, min(1.0, float(item.confidence)))

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

    logger.info("Extracted %d fields for document %s (type: %s)", len(inserted), document_id, doc_type)
    return inserted


def _effective_value(ef: ExtractedField) -> str:
    """Return the best available value for a field (corrected > normalized > raw)."""
    if ef.corrected_value:
        return ef.corrected_value.strip()
    return (ef.value_normalized or ef.value_raw).strip()


def _values_match(field_name: str, a: str, b: str) -> bool:
    """Return True if two field values are considered equivalent."""
    if field_name in _DECIMAL_FIELD_NAMES:
        try:
            return Decimal(a) == Decimal(b)
        except InvalidOperation:
            pass
    return a.lower() == b.lower()


async def detect_shipment_mismatches(
    shipment_id: uuid.UUID, db: AsyncSession
) -> list[dict]:
    """
    Compare extracted field values across all documents in a shipment.
    Returns a list of mismatch dicts for fields where documents disagree.
    """
    result = await db.execute(
        select(ExtractedField).where(
            ExtractedField.shipment_id == shipment_id,
            ExtractedField.field_name.in_(MISMATCH_CHECK_FIELDS),
        )
    )
    all_fields = list(result.scalars())

    # Group by field_name → document_id → best field (highest confidence)
    by_field: dict[str, dict[str, ExtractedField]] = {}
    for f in all_fields:
        doc_key = str(f.document_id)
        if f.field_name not in by_field:
            by_field[f.field_name] = {}
        existing = by_field[f.field_name].get(doc_key)
        if existing is None or f.confidence > existing.confidence:
            by_field[f.field_name][doc_key] = f

    mismatches = []
    for field_name, by_doc in by_field.items():
        if len(by_doc) < 2:
            continue  # only one document has this field — nothing to compare

        doc_fields = list(by_doc.values())
        effective = [_effective_value(ef) for ef in doc_fields]

        # Check if all values agree
        all_match = all(_values_match(field_name, effective[0], v) for v in effective[1:])
        if all_match:
            continue

        mismatches.append({
            "field_name": field_name,
            "severity": "error" if field_name in MISMATCH_CRITICAL_FIELDS else "warning",
            "values": [
                {
                    "document_id": ef.document_id,
                    "value_raw": ef.value_raw,
                    "value_normalized": ef.value_normalized,
                    "confidence": ef.confidence,
                }
                for ef in doc_fields
            ],
        })

    return mismatches


# ── Product mismatch detection ────────────────────────────────────────────────

import re as _re

_PRODUCT_COMPARE_FIELDS: list[tuple[str, str, str]] = [
    # (field_attr, display_label, severity)
    ("existing_hs_code", "HS Code",             "error"),
    ("quantity",         "Quantity",             "error"),
    ("unit_price",       "Unit Price",           "error"),
    ("currency",         "Currency",             "error"),
    ("origin_country",   "Country of Origin",    "warning"),
    ("destination_country", "Destination Country", "warning"),
]

_PRODUCT_DECIMAL_FIELDS: frozenset[str] = frozenset({"quantity", "unit_price"})


def _extract_number(s: str) -> Decimal | None:
    """Pull the leading numeric portion from a string (handles '1kg', '5.20 GBP', etc.)."""
    m = _re.match(r"^\s*([0-9]+\.?[0-9]*)", s.strip())
    if m:
        try:
            return Decimal(m.group(1))
        except InvalidOperation:
            pass
    return None


def _product_values_match(field_name: str, a: str, b: str) -> bool:
    if field_name in _PRODUCT_DECIMAL_FIELDS:
        na, nb = _extract_number(a), _extract_number(b)
        if na is not None and nb is not None:
            return na == nb
    return a.strip().lower() == b.strip().lower()


def _product_key(product) -> tuple[str, str] | None:
    """Return (key_type, key_value) for grouping. HS code preferred; fall back to name."""
    hs = (product.existing_hs_code or "").strip().replace(" ", "").upper()
    if hs and hs.lower() not in ("null", "none", ""):
        return ("hs", hs)
    name = (product.product_name or "").strip().lower()
    if name:
        return ("name", name)
    return None


async def detect_product_mismatches(
    shipment_id: uuid.UUID, db: AsyncSession
) -> tuple[list[dict], list[dict]]:
    """
    Compare DocumentProduct rows across documents in a shipment.

    Returns (group_mismatches, unmatched_products):
    - group_mismatches: products matched by HS code/name across 2+ docs with field differences
    - unmatched_products: products present in one doc but absent from other docs that have products
    """
    from app.modules.classification_api.models import DocumentProduct

    result = await db.execute(
        select(DocumentProduct).where(DocumentProduct.shipment_id == shipment_id)
    )
    all_products = list(result.scalars())

    # Need products from at least 2 different documents
    docs_with_products: set[str] = {str(p.document_id) for p in all_products}
    if len(docs_with_products) < 2:
        return [], []

    # Group: key → doc_id → [products]
    by_key: dict[tuple, dict[str, list]] = {}
    for p in all_products:
        key = _product_key(p)
        if key is None:
            continue
        doc_id = str(p.document_id)
        if key not in by_key:
            by_key[key] = {}
        by_key[key].setdefault(doc_id, []).append(p)

    group_mismatches: list[dict] = []
    unmatched_products: list[dict] = []

    for (key_type, key_value), by_doc in by_key.items():
        if len(by_doc) < 2:
            # Product exists in only one document; other documents with products don't have it
            present_doc_id = next(iter(by_doc))
            missing_in = [
                uuid.UUID(d) for d in docs_with_products if d != present_doc_id
            ]
            if missing_in:
                product = by_doc[present_doc_id][0]
                unit = str(product.unit_price).strip() if product.unit_price is not None else None
                if unit and unit.lower() in ("none", "null", ""):
                    unit = None
                unmatched_products.append({
                    "document_id": product.document_id,
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "hs_code": product.existing_hs_code,
                    "quantity": str(product.quantity).strip() if product.quantity is not None else None,
                    "unit_price": unit,
                    "currency": product.currency,
                    "missing_in": missing_in,
                })
            continue

        # Product present in 2+ documents — compare field by field
        field_mismatches: list[dict] = []

        for field_attr, display_label, severity in _PRODUCT_COMPARE_FIELDS:
            per_doc_values: list[dict] = []
            for doc_id, prods in by_doc.items():
                p = prods[0]
                raw = getattr(p, field_attr, None)
                if raw is None:
                    continue
                val = str(raw).strip()
                if not val or val.lower() in ("none", "null", ""):
                    continue
                per_doc_values.append({
                    "document_id": p.document_id,
                    "product_id": p.id,
                    "product_name": p.product_name,
                    "value": val,
                })

            if len(per_doc_values) < 2:
                continue

            first = per_doc_values[0]["value"]
            all_match = all(
                _product_values_match(field_attr, first, v["value"])
                for v in per_doc_values[1:]
            )
            if all_match:
                continue

            field_mismatches.append({
                "field_name": field_attr,
                "display_label": display_label,
                "severity": severity,
                "values": per_doc_values,
            })

        if not field_mismatches:
            continue

        sample = list(by_doc.values())[0][0]
        group_mismatches.append({
            "product_key": key_value,
            "hs_code": sample.existing_hs_code if key_type == "hs" else None,
            "field_mismatches": field_mismatches,
        })

    return group_mismatches, unmatched_products
