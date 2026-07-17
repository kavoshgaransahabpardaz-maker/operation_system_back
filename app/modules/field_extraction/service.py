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


def _norm_hs(hs: str | None) -> str:
    """Normalise an HS code: strip spaces, dots, uppercase."""
    if not hs:
        return ""
    return hs.strip().replace(" ", "").replace(".", "").upper()


def _product_name_key(name: str | None) -> str:
    return (name or "").strip().lower()


def _best_match_in_list(product, candidates: list):
    """
    Find the best matching product in candidates.
    Prefer HS code match; fall back to product name match.
    Returns the matched candidate or None.
    """
    ci_hs = _norm_hs(product.existing_hs_code)
    ci_name = _product_name_key(product.product_name)

    # Try HS code match first
    if ci_hs:
        for c in candidates:
            if _norm_hs(c.existing_hs_code) == ci_hs:
                return c

    # Fall back to name match
    if ci_name:
        for c in candidates:
            if _product_name_key(c.product_name) == ci_name:
                return c

    return None


async def detect_product_mismatches(
    shipment_id: uuid.UUID, db: AsyncSession
) -> tuple[list[dict], list[dict]]:
    """
    Compare product lines between the Commercial Invoice and the Packing List.

    Strategy:
    - Product list is sourced from CI (authoritative).
    - If both CI and PL have products, match each CI product to a PL product
      (by HS code first, then by product name) and compare HS codes.
    - Products in CI with no PL counterpart → unmatched (missing from PL).
    - Products in PL with no CI counterpart → unmatched (extra in PL).
    - If only one of CI/PL has products, no comparison is possible → return empty.

    Returns (hs_mismatches, unmatched_products).
    """
    from app.modules.classification_api.models import DocumentProduct
    from app.modules.document_classification.models import ClassificationResult, DocumentType

    # Load all products for this shipment
    prod_result = await db.execute(
        select(DocumentProduct).where(DocumentProduct.shipment_id == shipment_id)
    )
    all_products = list(prod_result.scalars())

    if not all_products:
        return [], []

    # Load doc types for all document_ids that have products
    doc_ids = list({p.document_id for p in all_products})
    cls_result = await db.execute(
        select(ClassificationResult).where(ClassificationResult.document_id.in_(doc_ids))
    )
    doc_type_map: dict[str, str] = {
        str(r.document_id): r.doc_type.value for r in cls_result.scalars()
    }

    # Split into CI products and PL products
    ci_products: list = []
    pl_products: list = []
    for p in all_products:
        dt = doc_type_map.get(str(p.document_id), "")
        if dt == DocumentType.COMMERCIAL_INVOICE.value:
            ci_products.append(p)
        elif dt == DocumentType.PACKING_LIST.value:
            pl_products.append(p)

    # Comparison only makes sense when both CI and PL have products
    if not ci_products or not pl_products:
        return [], []

    hs_mismatches: list[dict] = []
    unmatched_products: list[dict] = []
    matched_pl_ids: set[uuid.UUID] = set()

    for ci_p in ci_products:
        pl_p = _best_match_in_list(ci_p, pl_products)

        if pl_p is None:
            # CI product has no counterpart in PL
            unmatched_products.append({
                "document_id": ci_p.document_id,
                "product_id": ci_p.id,
                "product_name": ci_p.product_name,
                "hs_code": ci_p.existing_hs_code,
                "quantity": str(ci_p.quantity).strip() if ci_p.quantity else None,
                "unit_price": str(ci_p.unit_price).strip() if ci_p.unit_price else None,
                "currency": ci_p.currency,
                "missing_in": [pl_p2.document_id for pl_p2 in pl_products[:1]],
            })
            continue

        matched_pl_ids.add(pl_p.id)

        # Compare HS codes
        ci_hs = _norm_hs(ci_p.existing_hs_code)
        pl_hs = _norm_hs(pl_p.existing_hs_code)

        # Only flag when both sides have an HS code and they differ
        if ci_hs and pl_hs and ci_hs != pl_hs:
            hs_mismatches.append({
                "product_key": ci_p.product_name or ci_hs,
                "hs_code": ci_p.existing_hs_code,
                "field_mismatches": [{
                    "field_name": "existing_hs_code",
                    "display_label": "HS Code",
                    "severity": "error",
                    "values": [
                        {
                            "document_id": ci_p.document_id,
                            "product_id": ci_p.id,
                            "product_name": ci_p.product_name,
                            "value": ci_p.existing_hs_code,
                        },
                        {
                            "document_id": pl_p.document_id,
                            "product_id": pl_p.id,
                            "product_name": pl_p.product_name,
                            "value": pl_p.existing_hs_code,
                        },
                    ],
                }],
            })

    # PL products that had no CI counterpart
    for pl_p in pl_products:
        if pl_p.id not in matched_pl_ids:
            unmatched_products.append({
                "document_id": pl_p.document_id,
                "product_id": pl_p.id,
                "product_name": pl_p.product_name,
                "hs_code": pl_p.existing_hs_code,
                "quantity": str(pl_p.quantity).strip() if pl_p.quantity else None,
                "unit_price": str(pl_p.unit_price).strip() if pl_p.unit_price else None,
                "currency": pl_p.currency,
                "missing_in": [ci_p2.document_id for ci_p2 in ci_products[:1]],
            })

    return hs_mismatches, unmatched_products
