import logging
import uuid

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.agents.email_collector.tasks.sync_mailbox", bind=True, max_retries=3)
def sync_mailbox(self, connection_id: str):
    from app.modules.email_integration.models import MailboxConnection
    from app.modules.email_integration.service import sync_imap_connection

    with SyncSessionLocal() as db:
        conn = db.query(MailboxConnection).filter(
            MailboxConnection.id == uuid.UUID(connection_id),
            MailboxConnection.is_active == True,
        ).first()

        if not conn:
            logger.warning(f"Mailbox connection {connection_id} not found or inactive")
            return

        try:
            result = sync_imap_connection(db, conn)
            logger.info(f"Synced {connection_id}: {result['downloaded']} attachments downloaded")
            return result
        except Exception as exc:
            logger.error(f"Sync failed for {connection_id}: {exc}")
            raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="app.agents.email_collector.tasks.sync_all_mailboxes")
def sync_all_mailboxes():
    from app.modules.email_integration.models import MailboxConnection

    with SyncSessionLocal() as db:
        connections = db.query(MailboxConnection).filter(MailboxConnection.is_active == True).all()
        for conn in connections:
            sync_mailbox.apply_async(args=[str(conn.id)], queue="email")
        logger.info(f"Queued sync for {len(connections)} mailbox connections")
