import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.email_integration.models import EmailProvider


class ImapConnectionCreate(BaseModel):
    email_address: str
    imap_host: str
    imap_port: int = 993
    password: str


class MailboxConnectionOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: EmailProvider
    email_address: str
    last_synced_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailRecordOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    connection_id: uuid.UUID
    subject: str | None
    sender: str | None
    recipient: str | None
    received_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OAuthCallbackData(BaseModel):
    code: str
    state: str | None = None
