import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.document_storage.models import DocumentSource, DocumentStatus


class DocumentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    source: DocumentSource
    status: DocumentStatus
    shipment_id: uuid.UUID | None
    uploaded_by: uuid.UUID | None
    created_at: datetime
    download_url: str | None = None

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    source: DocumentSource
    status: DocumentStatus
    shipment_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
