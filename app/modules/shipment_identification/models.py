import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReferenceType(str, enum.Enum):
    BL = "bl"
    AWB = "awb"
    INVOICE = "invoice"
    PO = "po"
    CONTAINER = "container"
    INTERNAL = "internal"


class ShipmentStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETE = "complete"
    ON_HOLD = "on_hold"


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[ShipmentStatus] = mapped_column(Enum(ShipmentStatus), nullable=False, default=ShipmentStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    references: Mapped[list["ShipmentReference"]] = relationship("ShipmentReference", back_populates="shipment")
    shipment_documents: Mapped[list["ShipmentDocument"]] = relationship(
        "ShipmentDocument", back_populates="shipment"
    )


class ShipmentReference(Base):
    __tablename__ = "shipment_references"
    __table_args__ = (UniqueConstraint("org_id", "ref_type", "ref_value", name="uq_org_ref_type_value"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ref_type: Mapped[ReferenceType] = mapped_column(Enum(ReferenceType), nullable=False)
    ref_value: Mapped[str] = mapped_column(String(255), nullable=False)

    shipment: Mapped[Shipment] = relationship("Shipment", back_populates="references")


class ShipmentDocument(Base):
    __tablename__ = "shipment_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    associated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    associated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    shipment: Mapped[Shipment] = relationship("Shipment", back_populates="shipment_documents")
