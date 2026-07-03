import asyncio
import logging
import uuid

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.extract_fields",
    bind=True,
    max_retries=3,
    queue="classification",
)
def extract_fields_task(self, document_id: str):
    """Extract fields from a classified document, then run mismatch comparison."""
    from app.core.database import AsyncSessionLocal
    from app.modules.field_extraction.service import extract_fields

    doc_uuid = uuid.UUID(document_id)

    async def _run_extraction():
        async with AsyncSessionLocal() as db:
            try:
                fields = await extract_fields(doc_uuid, db)
                logger.info(
                    "Extracted %d fields for document %s", len(fields), document_id
                )
                return fields
            except Exception as exc:
                logger.error("Field extraction failed for %s: %s", document_id, exc)
                raise

    try:
        fields = asyncio.run(_run_extraction())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)

    # Determine shipment_id from first field and run comparison
    if fields:
        shipment_id = fields[0].shipment_id
        if shipment_id:
            run_comparison_task.apply_async(args=[str(shipment_id)], queue="classification")
            logger.info("Queued comparison for shipment %s", shipment_id)


@celery_app.task(
    name="tasks.run_comparison",
    bind=True,
    max_retries=3,
    queue="classification",
)
def run_comparison_task(self, shipment_id: str):
    """Run mismatch comparison for all fields in a shipment."""
    from app.core.database import AsyncSessionLocal
    from app.modules.flags.service import run_comparison_and_create_flags

    ship_uuid = uuid.UUID(shipment_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            await run_comparison_and_create_flags(ship_uuid, db)

    try:
        asyncio.run(_run())
        logger.info("Comparison completed for shipment %s", shipment_id)
    except Exception as exc:
        logger.error("Comparison failed for shipment %s: %s", shipment_id, exc)
        raise self.retry(exc=exc, countdown=60)
