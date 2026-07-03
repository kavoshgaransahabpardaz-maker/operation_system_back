import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FlagType(str, enum.Enum):
    MISSING_DOCUMENT = "missing_document"
    MISSING_FIELD = "missing_field"
    MISMATCH = "mismatch"
    LOW_CONFIDENCE = "low_confidence"
    HS_INCONSISTENCY = "hs_inconsistency"


class FlagSeverity(str, enum.Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class FlagStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class ResolutionDecision(str, enum.Enum):
    ACCEPTED = "accepted"
    OVERRIDDEN = "overridden"
    DISMISSED = "dismissed"


class Flag(Base):
    __tablename__ = "flags"
    __table_args__ = (
        Index("ix_flags_shipment_id", "shipment_id"),
        Index("ix_flags_org_id", "org_id"),
        Index("ix_flags_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    flag_type: Mapped[FlagType] = mapped_column(Enum(FlagType), nullable=False)
    severity: Mapped[FlagSeverity] = mapped_column(Enum(FlagSeverity), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflicting_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[FlagStatus] = mapped_column(
        Enum(FlagStatus), nullable=False, default=FlagStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FlagResolution(Base):
    __tablename__ = "flag_resolutions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flags.id"), nullable=False, index=True
    )
    resolved_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[ResolutionDecision] = mapped_column(Enum(ResolutionDecision), nullable=False)
    chosen_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
