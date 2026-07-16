import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.classification_api.models import DocumentProduct
from app.modules.document_classification.models import ClassificationResult
from app.modules.document_storage.models import Document, DocumentStatus
from app.modules.field_extraction.models import ExtractedField, ExtractedFieldStatus
from app.modules.shipment_identification import service
from app.modules.shipment_identification.models import (
    ReferenceType,
    Shipment,
    ShipmentDocument,
    ShipmentReference,
    ShipmentStatus,
)
from app.modules.shipment_identification.schemas import (
    DocumentSummaryOut,
    ReassociateRequest,
    ShipmentCreate,
    ShipmentDetailOut,
    ShipmentOut,
    ShipmentUpdate,
)
from app.modules.user_management.models import User

router = APIRouter(prefix="/shipments", tags=["Shipments"])


@router.post("/", response_model=ShipmentDetailOut, status_code=201)
async def create_shipment(
    data: ShipmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new shipment keyed by invoice number."""
    invoice_number = data.invoice_number.strip()
    if not invoice_number:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invoice_number is required")

    # Prevent duplicate invoice refs in the same org
    existing_ref = await db.execute(
        select(ShipmentReference).where(
            ShipmentReference.org_id == current_user.org_id,
            ShipmentReference.ref_type == ReferenceType.INVOICE,
            ShipmentReference.ref_value == invoice_number,
        )
    )
    if existing_ref.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A shipment with invoice number '{invoice_number}' already exists",
        )

    shipment = Shipment(org_id=current_user.org_id, status=ShipmentStatus.ACTIVE)
    db.add(shipment)
    await db.flush()

    db.add(ShipmentReference(
        shipment_id=shipment.id,
        org_id=current_user.org_id,
        ref_type=ReferenceType.INVOICE,
        ref_value=invoice_number,
    ))
    await db.commit()

    result = await db.execute(
        select(Shipment)
        .where(Shipment.id == shipment.id)
        .options(selectinload(Shipment.references))
    )
    shipment = result.scalar_one()
    return ShipmentDetailOut(
        id=shipment.id,
        org_id=shipment.org_id,
        status=shipment.status,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        references=list(shipment.references),
        documents=[],
    )


@router.get("/", response_model=list[ShipmentOut])
async def list_shipments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Shipment)
        .where(Shipment.org_id == current_user.org_id)
        .options(selectinload(Shipment.references))
        .order_by(Shipment.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{shipment_id}", response_model=ShipmentDetailOut)
async def get_shipment(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Shipment)
        .where(Shipment.id == shipment_id, Shipment.org_id == current_user.org_id)
        .options(selectinload(Shipment.references))
    )
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")

    # Load documents linked to this shipment
    docs_result = await db.execute(
        select(Document).where(Document.shipment_id == shipment_id).order_by(Document.created_at)
    )
    docs = list(docs_result.scalars().all())

    if not docs:
        return ShipmentDetailOut(
            id=shipment.id,
            org_id=shipment.org_id,
            status=shipment.status,
            created_at=shipment.created_at,
            updated_at=shipment.updated_at,
            references=list(shipment.references),
            documents=[],
        )

    doc_ids = [d.id for d in docs]

    # Batch: classification results
    cls_result = await db.execute(
        select(ClassificationResult).where(ClassificationResult.document_id.in_(doc_ids))
    )
    cls_by_doc: dict[uuid.UUID, ClassificationResult] = {
        c.document_id: c for c in cls_result.scalars()
    }

    # Batch: field counts per document
    field_count_result = await db.execute(
        select(ExtractedField.document_id, func.count().label("cnt"))
        .where(ExtractedField.document_id.in_(doc_ids))
        .group_by(ExtractedField.document_id)
    )
    field_counts: dict[uuid.UUID, int] = {r.document_id: r.cnt for r in field_count_result}

    # Batch: confirmed+corrected field counts per document
    confirmed_result = await db.execute(
        select(ExtractedField.document_id, func.count().label("cnt"))
        .where(
            ExtractedField.document_id.in_(doc_ids),
            ExtractedField.status.in_([ExtractedFieldStatus.CONFIRMED, ExtractedFieldStatus.CORRECTED]),
        )
        .group_by(ExtractedField.document_id)
    )
    confirmed_counts: dict[uuid.UUID, int] = {r.document_id: r.cnt for r in confirmed_result}

    # Batch: product counts per document
    product_result = await db.execute(
        select(DocumentProduct.document_id, func.count().label("cnt"))
        .where(DocumentProduct.document_id.in_(doc_ids))
        .group_by(DocumentProduct.document_id)
    )
    product_counts: dict[uuid.UUID, int] = {r.document_id: r.cnt for r in product_result}

    document_summaries: list[DocumentSummaryOut] = []
    for doc in docs:
        cls = cls_by_doc.get(doc.id)
        document_summaries.append(DocumentSummaryOut(
            id=doc.id,
            filename=doc.filename,
            status=doc.status,
            doc_type=cls.doc_type if cls else None,
            doc_type_confidence=cls.confidence if cls else None,
            is_manual_override=cls.is_manual_override if cls else None,
            field_count=field_counts.get(doc.id, 0),
            confirmed_field_count=confirmed_counts.get(doc.id, 0),
            product_count=product_counts.get(doc.id, 0),
        ))

    return ShipmentDetailOut(
        id=shipment.id,
        org_id=shipment.org_id,
        status=shipment.status,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        references=list(shipment.references),
        documents=document_summaries,
    )


@router.patch("/{shipment_id}", response_model=ShipmentOut)
async def update_shipment(
    shipment_id: uuid.UUID,
    data: ShipmentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.update_shipment_status(db, current_user.org_id, shipment_id, data.status)


@router.delete("/{shipment_id}", status_code=204)
async def delete_shipment(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await service.delete_shipment(db, current_user.org_id, shipment_id)


@router.post("/documents/{document_id}/reassociate", status_code=204)
async def reassociate_document(
    document_id: uuid.UUID,
    data: ReassociateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    assoc_result = await db.execute(
        select(ShipmentDocument).where(ShipmentDocument.document_id == document_id)
    )
    assoc = assoc_result.scalar_one_or_none()
    if assoc:
        assoc.shipment_id = data.shipment_id
        assoc.associated_by = current_user.id
    else:
        db.add(ShipmentDocument(
            shipment_id=data.shipment_id, document_id=document_id, associated_by=current_user.id
        ))

    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if doc:
        doc.shipment_id = data.shipment_id
        doc.status = DocumentStatus.MATCHED
    await db.commit()
