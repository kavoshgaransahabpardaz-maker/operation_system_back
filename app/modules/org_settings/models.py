import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OrgSettings(Base):
    __tablename__ = "org_settings"
    __table_args__ = (UniqueConstraint("org_id", name="uq_org_settings_org_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, unique=True, index=True
    )
    weight_qty_tolerance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    value_tolerance_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    name_match_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.93)
    # Orchestration
    doc_organization_by: Mapped[str] = mapped_column(
        String(20), nullable=False, default="shipment"
    )  # shipment | client | lane | date
    auto_fix_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.95
    )  # auto-resolve mismatches above this confidence
    email_critical_alerts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )  # send email for impact_score >= 4 news
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
