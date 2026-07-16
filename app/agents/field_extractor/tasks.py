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
    """
    Call external classification API for a document, store products + extracted fields,
    auto-link shipment by invoice_number, then run flags and comparison.
    """
    from app.core import storage
    from app.core.database import AsyncSessionLocal
    from app.modules.classification_api.service import (
        call_classification_api,
        link_document_to_shipment_by_invoice,
        process_classification_result,
    )
    from app.modules.document_storage.models import Document
    from sqlalchemy import select

    doc_uuid = uuid.UUID(document_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            # Load document
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            # Download file from S3
            file_bytes = storage.download_bytes(doc.file_key)
            logger.info("Downloaded %d bytes for document %s", len(file_bytes), document_id)

            # Call external classification API
            api_response = await call_classification_api(file_bytes, doc.filename)
            logger.info(
                "Classification API returned %d products for document %s",
                len(api_response.get("products") or []),
                document_id,
            )

            # Auto-link shipment by invoice_number (before saving fields so shipment_id is set)
            shipment_data = api_response.get("shipment") or {}
            invoice_number = shipment_data.get("invoice_number")
            shipment_id = None
            if invoice_number:
                try:
                    shipment_id = await link_document_to_shipment_by_invoice(
                        doc_uuid, str(invoice_number), doc.org_id, db
                    )
                    # Refresh doc to pick up new shipment_id
                    await db.refresh(doc)
                except Exception as exc:
                    logger.warning(
                        "Shipment auto-link failed for invoice_number=%s: %s",
                        invoice_number, exc,
                    )

            # Map API response to ExtractedField + DocumentProduct rows
            extracted, products = await process_classification_result(doc_uuid, api_response, db)

            # Backfill shipment_id on new rows if linking happened after initial processing
            if shipment_id:
                for ef in extracted:
                    ef.shipment_id = shipment_id
                for dp in products:
                    dp.shipment_id = shipment_id

            await db.commit()
            for ef in extracted:
                await db.refresh(ef)

            logger.info(
                "Saved %d extracted fields, %d products for document %s",
                len(extracted), len(products), document_id,
            )
            return extracted, shipment_id

    try:
        extracted, shipment_id = asyncio.run(_run())
    except Exception as exc:
        logger.error("Classification API extraction failed for %s: %s", document_id, exc)
        raise self.retry(exc=exc, countdown=60)

    if not extracted:
        return

    org_id = extracted[0].org_id if extracted else None

    # Run missing-field flags for this document
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
            from app.modules.intel.sanctions import screen_shipment_parties
            await screen_shipment_parties(ship_uuid, db)

    try:
        asyncio.run(_run())
        logger.info("Comparison + sanctions screen completed for shipment %s", shipment_id)
    except Exception as exc:
        logger.error("Comparison/sanctions failed for shipment %s: %s", shipment_id, exc)
        raise self.retry(exc=exc, countdown=60)
