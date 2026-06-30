import logging
import uuid

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.agents.shipment_matcher.tasks.run_shipment_matching",
    bind=True,
    max_retries=3,
    queue="matching",
)
def run_shipment_matching(self, document_id: str):
    from app.modules.shipment_identification.service import identify_and_associate

    doc_uuid = uuid.UUID(document_id)

    with SyncSessionLocal() as db:
        try:
            shipment = identify_and_associate(db, doc_uuid)
            if shipment:
                logger.info(f"Document {document_id} matched to shipment {shipment.id}")
            else:
                logger.info(f"Document {document_id} could not be matched — marked unmatched")
        except Exception as exc:
            logger.error(f"Shipment matching failed for {document_id}: {exc}")
            raise self.retry(exc=exc, countdown=30)
