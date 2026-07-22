import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentProduct(Base):
    """One row per product line extracted by the external classification API."""

    __tablename__ = "document_products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    material: Mapped[str | None] = mapped_column(Text, nullable=True)
    intended_use: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit_price: Mapped[str | None] = mapped_column(String(50), nullable=True)
    line_total: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ship_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    destination_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    existing_hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    existing_national_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    existing_national_code_jurisdiction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    net_weight: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gross_weight: Mapped[str | None] = mapped_column(String(50), nullable=True)
    missing_required_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_ready_to_classify: Mapped[bool] = mapped_column(Boolean, default=False)

    # HS Genie classification state
    hs_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    hs_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hs_verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Stores the id of the most recent HsGenieRun for this product (no FK to avoid circularity)
    active_genie_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class HsGenieRun(Base):
    """Audit record for every HS Genie run and Verify action on a product line."""

    __tablename__ = "hs_genie_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_products.id"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    path: Mapped[str] = mapped_column(String(10), nullable=False)        # 'verify' | 'genie'
    record_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # external API record_id
    candidates: Mapped[list | None] = mapped_column(JSON, nullable=True) # full candidate list
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # text sent to API

    chosen_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chosen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chosen_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    feedback_signal: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 'thumbs_up'|'thumbs_down'
    corrected_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
