import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

_DEFAULT_EMAIL_KEYWORDS = ["Commercial Invoice", "Packing list", "Bill of Materials"]


class EmailProvider(str, enum.Enum):
    GMAIL = "gmail"
    MICROSOFT365 = "microsoft365"
    OUTLOOK = "outlook"
    IMAP = "imap"


class MailboxConnection(Base):
    __tablename__ = "mailbox_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[EmailProvider] = mapped_column(Enum(EmailProvider), nullable=False)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_enc: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imap_password_enc: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Nullable: None means "download all attachments regardless of subject"
    email_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String(500)), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    email_records: Mapped[list["EmailRecord"]] = relationship("EmailRecord", back_populates="connection")


class EmailRecord(Base):
    __tablename__ = "email_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailbox_connections.id"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    connection: Mapped[MailboxConnection] = relationship("MailboxConnection", back_populates="email_records")
    attachments: Mapped[list["EmailAttachment"]] = relationship("EmailAttachment", back_populates="email_record")


class EmailAttachment(Base):
    __tablename__ = "email_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_records.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    email_record: Mapped[EmailRecord] = relationship("EmailRecord", back_populates="attachments")
