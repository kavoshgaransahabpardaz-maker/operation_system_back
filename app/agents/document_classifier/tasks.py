import logging
import uuid

from app.core.celery_app import celery_app
from app.core.database import SyncSessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.agents.document_classifier.tasks.run_ocr_then_classify",
    bind=True,
    max_retries=3,
    queue="classification",
)
def run_ocr_then_classify(self, document_id: str):
    from app.modules.ocr_processing.service import extract_text
    from app.modules.document_classification.service import classify_document

    doc_uuid = uuid.UUID(document_id)

    with SyncSessionLocal() as db:
        try:
            logger.info(f"Starting OCR for document {document_id}")
            extract_text(db, doc_uuid)
        except Exception as exc:
            logger.error(f"OCR failed for {document_id}: {exc}")
            raise self.retry(exc=exc, countdown=30)

        try:
            logger.info(f"Classifying document {document_id}")
            classify_document(db, doc_uuid)
        except Exception as exc:
            logger.error(f"Classification failed for {document_id}: {exc}")
            raise self.retry(exc=exc, countdown=30)

    # Chain to shipment matching
    from app.agents.shipment_matcher.tasks import run_shipment_matching
    run_shipment_matching.apply_async(args=[document_id], queue="matching")
    logger.info(f"Queued shipment matching for {document_id}")

    # Chain to field extraction
    from app.agents.field_extractor.tasks import extract_fields_task
    extract_fields_task.apply_async(args=[document_id], queue="classification")
    logger.info(f"Queued field extraction for {document_id}")
