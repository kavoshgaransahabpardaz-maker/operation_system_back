import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentType(str, enum.Enum):
    COMMERCIAL_INVOICE = "commercial_invoice"
    PACKING_LIST = "packing_list"
    BILL_OF_LADING = "bill_of_lading"
    AIR_WAYBILL = "air_waybill"
    CERTIFICATE_OF_ORIGIN = "certificate_of_origin"
    INSURANCE_CERTIFICATE = "insurance_certificate"
    CUSTOMS_DECLARATION = "customs_declaration"
    PURCHASE_ORDER = "purchase_order"
    DELIVERY_ORDER = "delivery_order"
    MILL_CERTIFICATE = "mill_certificate"
    SUPPLIERS_DECLARATION = "suppliers_declaration"
    CMR = "cmr"
    PHYTOSANITARY_CERTIFICATE = "phytosanitary_certificate"
    BILL_OF_MATERIAL = "bill_of_material"
    PRODUCT_SPECIFICATION = "product_specification"
    OTHER = "other"


class ClassificationResult(Base):
    __tablename__ = "classification_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), unique=True, nullable=False, index=True
    )
    doc_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    classified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
