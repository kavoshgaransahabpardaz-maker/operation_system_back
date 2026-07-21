import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.field_extraction.models import ExtractedFieldStatus, FieldType


class FieldName(str, enum.Enum):
    # ── Parties ──────────────────────────────────────────────────────────────
    PARTY_SHIPPER = "party_shipper"           # seller / consignor: name + address
    PARTY_CONSIGNEE = "party_consignee"       # buyer / consignee: name + address
    VAT_NUMBER_SELLER = "vat_number_seller"   # seller VAT / EIK (Bulgaria) / TVA etc.
    VAT_NUMBER_BUYER = "vat_number_buyer"     # buyer VAT number
    REX_NUMBER_SELLER = "rex_number_seller"   # seller Registered Exporter number
    REX_NUMBER_BUYER = "rex_number_buyer"     # buyer REX number
    EORI_NUMBER = "eori_number"               # Economic Operators Registration & ID

    # ── Financials ───────────────────────────────────────────────────────────
    INVOICE_VALUE = "invoice_value"
    VAT_VALUE = "vat_value"                   # VAT amount
    FREIGHT_VALUE = "freight_value"           # freight cost
    INSURANCE_VALUE = "insurance_value"       # insurance cost
    CURRENCY = "currency"

    # ── Weights & measures ───────────────────────────────────────────────────
    GROSS_WEIGHT = "gross_weight"
    NET_WEIGHT = "net_weight"
    QUANTITY = "quantity"
    TOTAL_PACKAGES = "total_packages"

    # ── Product ──────────────────────────────────────────────────────────────
    HS_CODE = "hs_code"
    COMMODITY_DESCRIPTION = "commodity_description"
    LOT_NUMBER = "lot_number"
    PRODUCT_REGISTRATION_NUMBER = "product_registration_number"
    PRODUCT_SERIAL_NUMBER = "product_serial_number"

    # ── Trade terms & compliance ─────────────────────────────────────────────
    STATED_ORIGIN = "stated_origin"
    DESTINATION_COUNTRY = "destination_country"
    PLACE_OF_LOADING = "place_of_loading"
    PORT_OF_DISCHARGE = "port_of_discharge"
    INCOTERM = "incoterm"
    PREFERENTIAL_DUTY = "preferential_duty"   # self-certification statement text or "yes"

    # ── Dates ────────────────────────────────────────────────────────────────
    INVOICE_DATE = "invoice_date"
    DUE_DATE = "due_date"
    SHIPMENT_DATE = "shipment_date"
    EXPIRY_DATE = "expiry_date"

    # ── Identifiers ──────────────────────────────────────────────────────────
    REFERENCE = "reference"                   # invoice / packing-list number
    LOCAL_REFERENCE = "local_reference"
    POINT_OF_ENTRY = "point_of_entry"

    # ── Additional financials ─────────────────────────────────────────────────
    FOB_VALUE = "fob_value"                   # Free On Board value
    WEIGHT_UNIT = "weight_unit"               # unit for weight fields (kg, lbs, etc.)


class ExtractedFieldOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    shipment_id: uuid.UUID | None
    org_id: uuid.UUID | None
    field_name: str
    value_raw: str
    value_normalized: str | None
    field_type: str | None
    confidence: float
    page_number: int | None
    status: ExtractedFieldStatus
    confirmed_at: datetime | None
    confirmed_by: uuid.UUID | None
    corrected_value: str | None
    corrected_by: uuid.UUID | None
    corrected_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FieldCorrectRequest(BaseModel):
    corrected_value: str


# Internal Pydantic schema for validating LLM JSON output
class LLMFieldItem(BaseModel):
    field_name: str
    value_raw: str
    confidence: float
    page_number: int | None = None


class LLMFieldsResponse(BaseModel):
    fields: list[LLMFieldItem]


# ── Shipment-level field mismatch (across documents) ─────────────────────────

class MismatchValue(BaseModel):
    document_id: uuid.UUID
    value_raw: str
    value_normalized: str | None
    confidence: float


class FieldMismatch(BaseModel):
    field_name: str
    severity: Literal["warning", "error"]
    values: list[MismatchValue]


# ── Product-level mismatch (same product, different values across documents) ──

class ProductMismatchValue(BaseModel):
    document_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str | None
    value: str


class ProductFieldMismatch(BaseModel):
    field_name: str                           # "quantity", "unit_price", "existing_hs_code", …
    display_label: str                        # human-readable
    severity: Literal["warning", "error"]
    values: list[ProductMismatchValue]


class ProductGroupMismatch(BaseModel):
    product_key: str                          # HS code (preferred) or product name
    hs_code: str | None                       # HS code if matching was hs-based
    field_mismatches: list[ProductFieldMismatch]


class UnmatchedProduct(BaseModel):
    document_id: uuid.UUID                    # which document HAS this product
    product_id: uuid.UUID
    product_name: str | None
    hs_code: str | None
    quantity: str | None
    unit_price: str | None
    currency: str | None
    missing_in: list[uuid.UUID]               # document ids that have products but NOT this one


# ── Combined response ─────────────────────────────────────────────────────────

class ShipmentMismatchOut(BaseModel):
    shipment_id: uuid.UUID
    mismatches: list[FieldMismatch]           # shipment/document-level field mismatches
    product_mismatches: list[ProductGroupMismatch] = []  # matched products with differing fields
    unmatched_products: list[UnmatchedProduct] = []      # products present in some docs but missing from others
