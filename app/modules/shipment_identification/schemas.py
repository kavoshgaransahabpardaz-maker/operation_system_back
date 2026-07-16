import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.document_classification.models import DocumentType
from app.modules.document_storage.models import DocumentStatus
from app.modules.shipment_identification.models import ReferenceType, ShipmentStatus


class ShipmentCreate(BaseModel):
    invoice_number: str


class ShipmentReferenceOut(BaseModel):
    id: uuid.UUID
    ref_type: ReferenceType
    ref_value: str

    model_config = {"from_attributes": True}


class ShipmentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    status: ShipmentStatus
    created_at: datetime
    updated_at: datetime
    references: list[ShipmentReferenceOut] = []

    model_config = {"from_attributes": True}


class DocumentSummaryOut(BaseModel):
    """Lightweight document summary shown inside ShipmentDetailOut."""
    id: uuid.UUID
    filename: str
    status: DocumentStatus
    doc_type: DocumentType | None = None
    doc_type_confidence: float | None = None
    is_manual_override: bool | None = None
    # Field extraction stats
    field_count: int = 0
    confirmed_field_count: int = 0  # status in (confirmed, corrected)
    product_count: int = 0

    model_config = {"from_attributes": True}


class ShipmentDetailOut(BaseModel):
    """Shipment with full document list and extraction stats."""
    id: uuid.UUID
    org_id: uuid.UUID
    status: ShipmentStatus
    created_at: datetime
    updated_at: datetime
    references: list[ShipmentReferenceOut] = []
    documents: list[DocumentSummaryOut] = []

    model_config = {"from_attributes": True}


class ReassociateRequest(BaseModel):
    shipment_id: uuid.UUID


class ShipmentUpdate(BaseModel):
    status: ShipmentStatus
