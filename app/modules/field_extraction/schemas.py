import enum
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.field_extraction.models import ExtractedFieldStatus, FieldType


class FieldName(str, enum.Enum):
    PARTY_SHIPPER = "party_shipper"
    PARTY_CONSIGNEE = "party_consignee"
    INVOICE_VALUE = "invoice_value"
    CURRENCY = "currency"
    GROSS_WEIGHT = "gross_weight"
    NET_WEIGHT = "net_weight"
    QUANTITY = "quantity"
    HS_CODE = "hs_code"
    STATED_ORIGIN = "stated_origin"
    INCOTERM = "incoterm"
    INVOICE_DATE = "invoice_date"
    SHIPMENT_DATE = "shipment_date"
    REFERENCE = "reference"


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
