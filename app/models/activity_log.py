import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActivityAction(str, enum.Enum):
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_CLASSIFIED = "document_classified"
    CLASSIFICATION_OVERRIDDEN = "classification_overridden"
    DOCUMENT_MATCHED = "document_matched"
    DOCUMENT_REASSOCIATED = "document_reassociated"
    SHIPMENT_CREATED = "shipment_created"
    SHIPMENT_STATUS_UPDATED = "shipment_status_updated"
    EMAIL_SYNCED = "email_synced"


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[ActivityAction] = mapped_column(Enum(ActivityAction), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
