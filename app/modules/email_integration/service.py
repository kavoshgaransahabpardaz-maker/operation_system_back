"""
Email integration service — runs synchronously inside Celery workers for sync jobs.
Async methods used for API routes (connection management).
"""
import io
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_token, encrypt_token
from app.modules.document_storage.models import DocumentSource
from app.modules.email_integration.models import (
    EmailAttachment,
    EmailProvider,
    EmailRecord,
    MailboxConnection,
)

SUPPORTED_ATTACHMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

EXTENSION_TO_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def create_imap_connection(
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    email_address: str,
    imap_host: str,
    imap_port: int,
    password: str,
) -> MailboxConnection:
    conn = MailboxConnection(
        org_id=org_id,
        user_id=user_id,
        provider=EmailProvider.IMAP,
        email_address=email_address,
        imap_host=imap_host,
        imap_port=imap_port,
        imap_password_enc=encrypt_token(password),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def sync_imap_connection(db: Session, connection: MailboxConnection) -> dict:
    import imapclient

    password = decrypt_token(connection.imap_password_enc)
    downloaded = 0
    errors = []

    with imapclient.IMAPClient(connection.imap_host, port=connection.imap_port, ssl=True) as client:
        client.login(connection.email_address, password)
        client.select_folder("INBOX")

        messages = client.search(["NOT", "DELETED"])
        for msg_id in messages:
            raw = client.fetch([msg_id], ["RFC822"])
            import email as email_lib
            msg = email_lib.message_from_bytes(raw[msg_id][b"RFC822"])

            message_id = msg.get("Message-ID", f"imap-{connection.id}-{msg_id}")
            existing = db.query(EmailRecord).filter(EmailRecord.message_id == message_id).first()
            if existing:
                continue

            received_str = msg.get("Date")
            received_at = None
            if received_str:
                from email.utils import parsedate_to_datetime
                try:
                    received_at = parsedate_to_datetime(received_str)
                except Exception:
                    pass

            record = EmailRecord(
                org_id=connection.org_id,
                connection_id=connection.id,
                message_id=message_id,
                subject=msg.get("Subject"),
                sender=msg.get("From"),
                recipient=msg.get("To"),
                received_at=received_at,
            )
            db.add(record)
            db.flush()

            for part in msg.walk():
                if part.get_content_disposition() != "attachment":
                    continue
                filename = part.get_filename()
                if not filename:
                    continue

                import os
                ext = os.path.splitext(filename)[1].lower()
                content_type = EXTENSION_TO_MIME.get(ext)
                if not content_type:
                    continue

                data = part.get_payload(decode=True)
                if not data:
                    continue

                try:
                    from app.modules.document_storage.service import upload_document_sync
                    doc = upload_document_sync(
                        db=db,
                        file_obj=io.BytesIO(data),
                        filename=filename,
                        content_type=content_type,
                        size_bytes=len(data),
                        org_id=connection.org_id,
                        source=DocumentSource.EMAIL,
                    )
                    att = EmailAttachment(
                        email_record_id=record.id, filename=filename, document_id=doc.id
                    )
                    db.add(att)
                    downloaded += 1
                except Exception as e:
                    errors.append(str(e))

        db.commit()

    connection.last_synced_at = datetime.now(timezone.utc)
    db.commit()

    return {"downloaded": downloaded, "errors": errors}


def get_connections(db: Session, org_id: uuid.UUID) -> list[MailboxConnection]:
    return db.query(MailboxConnection).filter(
        MailboxConnection.org_id == org_id, MailboxConnection.is_active == True
    ).all()


async def create_imap_connection_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    email_address: str,
    imap_host: str,
    imap_port: int,
    password: str,
) -> MailboxConnection:
    conn = MailboxConnection(
        org_id=org_id,
        user_id=user_id,
        provider=EmailProvider.IMAP,
        email_address=email_address,
        imap_host=imap_host,
        imap_port=imap_port,
        imap_password_enc=encrypt_token(password),
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn
