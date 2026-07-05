import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProductRecord(Base):
    """Structured product/line-item data harvested from trade documents."""

    __tablename__ = "product_records"
    __table_args__ = (
        Index("ix_product_records_org_id", "org_id"),
        Index("ix_product_records_description_hash", "description_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True
    )
    hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stated_origin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    description_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    incoterm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ExtractedFieldStatus(str, enum.Enum):
    EXTRACTED = "extracted"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"


class FieldType(str, enum.Enum):
    STRING = "string"
    DECIMAL = "decimal"
    DATE = "date"
    ISO_CODE = "iso_code"


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        Index("ix_extracted_fields_document_id", "document_id"),
        Index("ix_extracted_fields_shipment_id", "shipment_id"),
        Index("ix_extracted_fields_org_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value_raw: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ExtractedFieldStatus] = mapped_column(
        Enum(ExtractedFieldStatus), nullable=False, default=ExtractedFieldStatus.EXTRACTED
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
