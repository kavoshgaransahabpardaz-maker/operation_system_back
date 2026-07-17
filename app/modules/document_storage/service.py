import hashlib
import io
import uuid
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core import storage
from app.modules.document_storage.models import Document, DocumentSource, DocumentStatus, DocumentVersion


def _compute_hash(file_obj: BinaryIO) -> tuple[str, bytes]:
    """Read file, compute SHA-256, return (hex_hash, bytes). Resets file position."""
    data = file_obj.read()
    content_hash = hashlib.sha256(data).hexdigest()
    return content_hash, data


def _check_duplicate_sync(db: Session, org_id: uuid.UUID, content_hash: str) -> Document | None:
    return db.query(Document).filter(
        Document.org_id == org_id, Document.content_hash == content_hash
    ).first()


async def _check_duplicate_async(db: AsyncSession, org_id: uuid.UUID, content_hash: str) -> Document | None:
    result = await db.execute(
        select(Document).where(Document.org_id == org_id, Document.content_hash == content_hash)
    )
    return result.scalar_one_or_none()


def upload_document_sync(
    db: Session,
    file_obj: BinaryIO,
    filename: str,
    content_type: str,
    size_bytes: int,
    org_id: uuid.UUID,
    source: DocumentSource,
    uploaded_by: uuid.UUID | None = None,
) -> Document:
    """Sync version for use in Celery tasks."""
    content_hash, data = _compute_hash(file_obj)

    existing = _check_duplicate_sync(db, org_id, content_hash)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "duplicate", "existing_document_id": str(existing.id)},
        )

    file_key = storage.upload_file(io.BytesIO(data), str(org_id), filename, content_type)
    doc_id = uuid.uuid4()
    doc = Document(
        id=doc_id,
        org_id=org_id,
        filename=filename,
        file_key=file_key,
        content_type=content_type,
        size_bytes=size_bytes,
        source=source,
        status=DocumentStatus.UPLOADED,
        uploaded_by=uploaded_by,
        content_hash=content_hash,
    )
    db.add(doc)
    db.flush()

    version = DocumentVersion(id=uuid.uuid4(), document_id=doc_id, version_number=1, file_key=file_key)
    db.add(version)
    db.flush()

    # Queue OCR + classification pipeline
    from app.agents.document_classifier.tasks import run_ocr_then_classify
    run_ocr_then_classify.apply_async(args=[str(doc.id)], queue="classification")

    return doc


async def upload_document(
    db: AsyncSession,
    file_obj: BinaryIO,
    filename: str,
    content_type: str,
    size_bytes: int,
    org_id: uuid.UUID,
    source: DocumentSource,
    uploaded_by: uuid.UUID | None = None,
    shipment_id: uuid.UUID | None = None,
) -> Document:
    content_hash, data = _compute_hash(file_obj)

    existing = await _check_duplicate_async(db, org_id, content_hash)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "duplicate", "existing_document_id": str(existing.id)},
        )

    file_key = storage.upload_file(io.BytesIO(data), str(org_id), filename, content_type)
    doc = Document(
        id=uuid.uuid4(),
        org_id=org_id,
        filename=filename,
        file_key=file_key,
        content_type=content_type,
        size_bytes=size_bytes,
        source=source,
        status=DocumentStatus.UPLOADED,
        uploaded_by=uploaded_by,
        content_hash=content_hash,
        shipment_id=shipment_id,
    )
    db.add(doc)

    version = DocumentVersion(id=uuid.uuid4(), document_id=doc.id, version_number=1, file_key=file_key)
    db.add(version)

    if shipment_id:
        from app.modules.shipment_identification.models import ShipmentDocument
        db.add(ShipmentDocument(shipment_id=shipment_id, document_id=doc.id, associated_by=uploaded_by))

    await db.commit()
    await db.refresh(doc)

    # Trigger OCR pipeline
    from app.agents.document_classifier.tasks import run_ocr_then_classify
    run_ocr_then_classify.apply_async(args=[str(doc.id)], queue="classification")

    return doc


async def get_document(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


async def list_documents(
    db: AsyncSession, org_id: uuid.UUID, shipment_id: uuid.UUID | None = None
) -> list[Document]:
    query = select(Document).where(Document.org_id == org_id)
    if shipment_id:
        query = query.where(Document.shipment_id == shipment_id)
    result = await db.execute(query.order_by(Document.created_at.desc()))
    return list(result.scalars().all())


async def list_duplicates(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> list[Document]:
    doc = await get_document(db, org_id, document_id)
    if not doc.content_hash:
        return []
    result = await db.execute(
        select(Document).where(
            Document.org_id == org_id,
            Document.content_hash == doc.content_hash,
            Document.id != document_id,
        )
    )
    return list(result.scalars().all())


async def get_download_url(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> str:
    doc = await get_document(db, org_id, document_id)
    return storage.get_presigned_url(doc.file_key)


async def update_status(db: AsyncSession, document_id: uuid.UUID, new_status: DocumentStatus) -> None:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc:
        doc.status = new_status
        await db.commit()


async def set_shipment(db: AsyncSession, document_id: uuid.UUID, shipment_id: uuid.UUID) -> None:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc:
        doc.shipment_id = shipment_id
        await db.commit()


async def delete_document(db: AsyncSession, org_id: uuid.UUID, document_id: uuid.UUID) -> None:
    from sqlalchemy import delete as sql_delete
    from app.modules.document_classification.models import ClassificationResult
    from app.modules.ocr_processing.models import OcrResult
    from app.modules.field_extraction.models import ExtractedField
    from app.modules.shipment_identification.models import ShipmentDocument
    from app.modules.classification_api.models import DocumentProduct

    doc = await get_document(db, org_id, document_id)

    # Remove related rows in dependency order
    await db.execute(sql_delete(DocumentProduct).where(DocumentProduct.document_id == document_id))
    await db.execute(sql_delete(ExtractedField).where(ExtractedField.document_id == document_id))
    await db.execute(sql_delete(ClassificationResult).where(ClassificationResult.document_id == document_id))
    await db.execute(sql_delete(OcrResult).where(OcrResult.document_id == document_id))
    await db.execute(sql_delete(DocumentVersion).where(DocumentVersion.document_id == document_id))
    await db.execute(sql_delete(ShipmentDocument).where(ShipmentDocument.document_id == document_id))
    await db.execute(sql_delete(Document).where(Document.id == document_id))
    await db.commit()

    # Delete file from object storage (after DB commit so failure doesn't leave orphan rows)
    try:
        storage.delete_file(doc.file_key)
    except Exception:
        pass  # S3 delete failure is non-fatal; the DB row is already gone
