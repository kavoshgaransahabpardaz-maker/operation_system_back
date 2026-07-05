import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.document_classification.models import DocumentType
from app.modules.document_storage.models import DocumentSource, DocumentStatus
from app.modules.email_integration.models import EmailProvider
from app.modules.shipment_identification.models import ReferenceType, ShipmentStatus


class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    source: DocumentSource
    status: DocumentStatus
    doc_type: DocumentType | None = None
    confidence: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecentEmailOut(BaseModel):
    id: uuid.UUID
    subject: str | None
    sender: str | None
    provider: EmailProvider
    received_at: datetime | None
    attachment_count: int = 0


class ShipmentReferenceOut(BaseModel):
    ref_type: ReferenceType
    ref_value: str


class ShipmentDetail(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    status: ShipmentStatus
    created_at: datetime
    updated_at: datetime
    references: list[ShipmentReferenceOut]
    documents: list[DocumentSummary]


class AttentionShipment(BaseModel):
    id: uuid.UUID
    short_id: str
    flag_count: int


class DashboardStats(BaseModel):
    total_shipments: int
    documents_imported_today: int
    unclassified_documents: int
    shipments_requiring_review: int
    recent_email_imports: list[RecentEmailOut]
    # Enhanced fields
    open_flags_critical: int = 0
    open_flags_warning: int = 0
    pending_field_reviews: int = 0
    attention_queue: list[AttentionShipment] = []
