"""
Classification API integration.
Calls the external extraction service (http://94.101.185.122:8000/api/v1/classification/extract)
with the uploaded PDF, then maps the structured response to:
  - DocumentProduct rows (one per product line)
  - ExtractedField rows (for the existing mismatch engine)
  - Shipment auto-linking by invoice_number
"""
import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.classification_api.models import DocumentProduct
from app.modules.document_storage.models import Document
from app.modules.field_extraction.models import ExtractedField, ExtractedFieldStatus, FieldType
from app.modules.field_extraction.normalizers import normalize_field
from app.modules.shipment_identification.models import (
    ReferenceType,
    Shipment,
    ShipmentDocument,
    ShipmentReference,
    ShipmentStatus,
)

logger = logging.getLogger(__name__)

_CLASSIFICATION_API_URL = "http://94.101.185.122:8000/api/v1/classification/extract"
_API_TIMEOUT = 120.0  # seconds

# ── Field mapping ─────────────────────────────────────────────────────────────

# Shipment-level fields: (api_key → (field_name, field_type))
_SHIPMENT_FIELD_MAP: list[tuple[str, str, str]] = [
    ("invoice_number", "reference", FieldType.STRING.value),
    ("invoice_date", "invoice_date", FieldType.DATE.value),
    ("currency", "currency", FieldType.ISO_CODE.value),
    ("incoterms", "incoterm", FieldType.ISO_CODE.value),
    ("port_of_loading", "place_of_loading", FieldType.STRING.value),
    ("total_value", "invoice_value", FieldType.DECIMAL.value),
]

# Per-product fields extracted once per document (first non-null wins for dedup fields)
_PRODUCT_COMMON_MAP: list[tuple[str, str, str]] = [
    ("origin_country", "stated_origin", FieldType.ISO_CODE.value),
    ("destination_country", "destination_country", FieldType.ISO_CODE.value),
    ("currency", "currency", FieldType.ISO_CODE.value),
]

# Per-product fields that produce one ExtractedField row per product
_PRODUCT_PER_ITEM_MAP: list[tuple[str, str, str]] = [
    ("product_name", "commodity_description", FieldType.STRING.value),
    ("existing_hs_code", "hs_code", FieldType.STRING.value),
    ("quantity", "quantity", FieldType.DECIMAL.value),
    ("unit_price", "invoice_value", FieldType.DECIMAL.value),
]


async def call_classification_api(file_bytes: bytes, filename: str) -> dict:
    """POST file to external classification API and return parsed JSON."""
    async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
        response = await client.post(
            _CLASSIFICATION_API_URL,
            files={"file": (filename, file_bytes, "application/pdf")},
            data={"text": ""},
        )
        response.raise_for_status()
        return response.json()


def _make_field(
    document_id: uuid.UUID,
    shipment_id: uuid.UUID | None,
    org_id: uuid.UUID,
    field_name: str,
    value_raw: str,
    field_type: str,
    confidence: float = 0.95,
    page_number: int | None = None,
) -> ExtractedField:
    value_normalized = normalize_field(field_name, value_raw)
    return ExtractedField(
        document_id=document_id,
        shipment_id=shipment_id,
        org_id=org_id,
        field_name=field_name,
        value_raw=str(value_raw),
        value_normalized=value_normalized,
        field_type=field_type,
        confidence=confidence,
        page_number=page_number,
        status=ExtractedFieldStatus.EXTRACTED,
    )


async def process_classification_result(
    document_id: uuid.UUID,
    api_response: dict,
    db: AsyncSession,
) -> tuple[list[ExtractedField], list[DocumentProduct]]:
    """
    Map the external API response to ExtractedField + DocumentProduct rows.
    Does NOT commit — caller commits after optionally setting shipment_id.
    """
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if not doc:
        raise ValueError(f"Document {document_id} not found")

    shipment_id = doc.shipment_id
    org_id = doc.org_id
    products_data: list[dict] = api_response.get("products") or []
    shipment_data: dict = api_response.get("shipment") or {}

    extracted: list[ExtractedField] = []
    products: list[DocumentProduct] = []
    seen_field_names: set[str] = set()

    # ── Shipment-level fields ─────────────────────────────────────────────────
    for api_key, field_name, ftype in _SHIPMENT_FIELD_MAP:
        raw = shipment_data.get(api_key)
        if raw is None:
            continue
        value_raw = str(raw).strip()
        if not value_raw or value_raw == "None":
            continue
        ef = _make_field(document_id, shipment_id, org_id, field_name, value_raw, ftype)
        db.add(ef)
        extracted.append(ef)
        seen_field_names.add(field_name)

    # ── Per-product common fields (first non-null per field_name wins) ────────
    for api_key, field_name, ftype in _PRODUCT_COMMON_MAP:
        if field_name in seen_field_names:
            continue
        for prod in products_data:
            raw = prod.get(api_key)
            if raw:
                ef = _make_field(document_id, shipment_id, org_id, field_name, str(raw), ftype)
                db.add(ef)
                extracted.append(ef)
                seen_field_names.add(field_name)
                break

    # ── Per-product line-item fields ──────────────────────────────────────────
    for prod in products_data:
        for api_key, field_name, ftype in _PRODUCT_PER_ITEM_MAP:
            raw = prod.get(api_key)
            if raw is None:
                continue
            value_raw = str(raw).strip()
            if not value_raw or value_raw == "None":
                continue
            # Skip hs_code / unit_price if null-equivalent
            if api_key == "existing_hs_code" and value_raw.lower() in ("null", "none", ""):
                continue
            ef = _make_field(document_id, shipment_id, org_id, field_name, value_raw, ftype, confidence=0.95)
            db.add(ef)
            extracted.append(ef)

    # ── DocumentProduct rows ──────────────────────────────────────────────────
    for prod in products_data:
        dp = DocumentProduct(
            document_id=document_id,
            shipment_id=shipment_id,
            org_id=org_id,
            product_name=prod.get("product_name"),
            material=prod.get("material"),
            intended_use=prod.get("intended_use"),
            description=prod.get("description"),
            quantity=prod.get("quantity"),
            unit_price=str(prod["unit_price"]) if prod.get("unit_price") is not None else None,
            currency=prod.get("currency"),
            origin_country=prod.get("origin_country"),
            destination_country=prod.get("destination_country"),
            existing_hs_code=prod.get("existing_hs_code"),
            missing_required_fields=prod.get("missing_required_fields") or prod.get("missing_fields"),
            is_ready_to_classify=bool(prod.get("is_ready_to_classify", False)),
        )
        db.add(dp)
        products.append(dp)

    return extracted, products


async def link_document_to_shipment_by_invoice(
    document_id: uuid.UUID,
    invoice_number: str,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> uuid.UUID:
    """
    Find or create a Shipment keyed by invoice_number, then link the document to it.
    If the document already belongs to a different shipment, add the invoice reference
    to that shipment instead of moving the document.
    Returns the resolved shipment_id.
    """
    invoice_number = invoice_number.strip()
    if not invoice_number:
        raise ValueError("invoice_number is empty")

    # Look for an existing invoice reference in this org
    ref_result = await db.execute(
        select(ShipmentReference).where(
            ShipmentReference.org_id == org_id,
            ShipmentReference.ref_type == ReferenceType.INVOICE,
            ShipmentReference.ref_value == invoice_number,
        )
    )
    existing_ref = ref_result.scalar_one_or_none()

    if existing_ref:
        shipment_id = existing_ref.shipment_id
    else:
        doc_result = await db.execute(select(Document).where(Document.id == document_id))
        doc = doc_result.scalar_one_or_none()

        if doc and doc.shipment_id:
            # Document already matched to a shipment — add the invoice ref to it
            shipment_id = doc.shipment_id
        else:
            # Create a new shipment
            new_shipment = Shipment(org_id=org_id, status=ShipmentStatus.ACTIVE)
            db.add(new_shipment)
            await db.flush()
            shipment_id = new_shipment.id

        # Record the invoice reference
        db.add(ShipmentReference(
            shipment_id=shipment_id,
            org_id=org_id,
            ref_type=ReferenceType.INVOICE,
            ref_value=invoice_number,
        ))

    # Link the document to the shipment
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if doc:
        doc.shipment_id = shipment_id

    # Create ShipmentDocument join row (unique per document_id)
    sd_result = await db.execute(
        select(ShipmentDocument).where(ShipmentDocument.document_id == document_id)
    )
    if not sd_result.scalar_one_or_none():
        db.add(ShipmentDocument(shipment_id=shipment_id, document_id=document_id))

    await db.commit()
    logger.info(
        "Document %s linked to shipment %s via invoice_number=%s",
        document_id, shipment_id, invoice_number,
    )
    return shipment_id
