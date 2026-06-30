import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.document_storage import service
from app.modules.document_storage.models import DocumentSource
from app.modules.document_storage.schemas import DocumentListOut, DocumentOut
from app.modules.user_management.models import User

router = APIRouter(prefix="/documents", tags=["Documents"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large (max 50MB)")

    doc = await service.upload_document(
        db=db,
        file_obj=io.BytesIO(contents),
        filename=file.filename or "untitled",
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(contents),
        org_id=current_user.org_id,
        source=DocumentSource.UPLOAD,
        uploaded_by=current_user.id,
    )
    return doc


@router.get("/", response_model=list[DocumentListOut])
async def list_documents(
    shipment_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.list_documents(db, current_user.org_id, shipment_id)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    doc = await service.get_document(db, current_user.org_id, document_id)
    url = await service.get_download_url(db, current_user.org_id, document_id)
    result = DocumentOut.model_validate(doc)
    result.download_url = url
    return result


@router.get("/{document_id}/duplicates", response_model=list[DocumentListOut])
async def get_duplicates(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.list_duplicates(db, current_user.org_id, document_id)
