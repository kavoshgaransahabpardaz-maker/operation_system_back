import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.document_classification.models import DocumentType


class ClassificationOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    doc_type: DocumentType
    confidence: float
    is_manual_override: bool
    classified_by: uuid.UUID | None
    classified_at: datetime

    model_config = {"from_attributes": True}


class ClassificationOverride(BaseModel):
    doc_type: DocumentType
