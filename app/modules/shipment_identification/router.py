import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.shipment_identification import service
from app.modules.shipment_identification.models import Shipment, ShipmentDocument, ShipmentReference
from app.modules.shipment_identification.schemas import ReassociateRequest, ShipmentOut, ShipmentUpdate
from app.modules.document_storage.models import Document, DocumentStatus
from app.modules.user_management.models import User

router = APIRouter(prefix="/shipments", tags=["Shipments"])


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


@router.get("/{shipment_id}", response_model=ShipmentOut)
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
    return shipment


@router.patch("/{shipment_id}", response_model=ShipmentOut)
async def update_shipment(
    shipment_id: uuid.UUID,
    data: ShipmentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.update_shipment_status(db, current_user.org_id, shipment_id, data.status)


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
