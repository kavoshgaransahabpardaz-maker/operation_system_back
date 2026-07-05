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
    """Extract fields from a classified document, run missing-field flags, then comparison."""
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

    # Run missing-field flags for this document
    if fields:
        shipment_id = fields[0].shipment_id
        org_id = fields[0].org_id

        async def _run_missing_field_flags():
            from app.core.database import AsyncSessionLocal
            from app.modules.document_classification.models import ClassificationResult
            from app.modules.flags.service import create_missing_field_flags
            from sqlalchemy import select

            if not shipment_id:
                return
            async with AsyncSessionLocal() as db:
                cls_result = await db.execute(
                    select(ClassificationResult).where(
                        ClassificationResult.document_id == doc_uuid
                    )
                )
                cr = cls_result.scalar_one_or_none()
                if cr:
                    await create_missing_field_flags(
                        document_id=doc_uuid,
                        doc_type=cr.doc_type.value,
                        shipment_id=shipment_id,
                        org_id=org_id,
                        db=db,
                    )

        try:
            asyncio.run(_run_missing_field_flags())
        except Exception as exc:
            logger.warning("Missing-field flag creation failed for %s: %s", document_id, exc)

        # Queue comparison + status update
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
    """Run mismatch comparison, missing-doc flags, and status update for a shipment."""
    from app.core.database import AsyncSessionLocal
    from app.modules.flags.service import create_missing_document_flags, run_comparison_and_create_flags
    from app.modules.shipment_identification.service import auto_update_shipment_status

    ship_uuid = uuid.UUID(shipment_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            await run_comparison_and_create_flags(ship_uuid, db)
            await create_missing_document_flags(ship_uuid, "default", None, db)
            await auto_update_shipment_status(ship_uuid, db)
            # Sanctions screening — screen party names against ingested sanctions lists
            from app.modules.intel.sanctions import screen_shipment_parties
            await screen_shipment_parties(ship_uuid, db)

    try:
        asyncio.run(_run())
        logger.info("Comparison + sanctions screen completed for shipment %s", shipment_id)
    except Exception as exc:
        logger.error("Comparison/sanctions failed for shipment %s: %s", shipment_id, exc)
        raise self.retry(exc=exc, countdown=60)
