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

MAX_FILE_SIZE = 1 * 1024 * 1024 * 1024  # 1 GB
MAX_DOCUMENTS_PER_BATCH = 15

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/csv",
    "application/xml",
    "text/xml",
    "application/octet-stream",  # fallback when browser doesn't detect type
}

ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png",
    ".xls", ".xlsx", ".doc", ".docx",
    ".csv", ".xml",
}


def _validate_file(filename: str, content_type: str, size_bytes: int) -> None:
    if size_bytes > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 1 GB)",
        )
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{ext}'. Allowed: PDF, JPEG, PNG, XLS, XLSX, DOCX, CSV, XML",
        )


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    contents = await file.read()
    _validate_file(file.filename or "untitled", file.content_type or "", len(contents))

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


@router.post("/upload/batch", response_model=list[DocumentOut], status_code=201)
async def upload_batch(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    if len(files) > MAX_DOCUMENTS_PER_BATCH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many files (max {MAX_DOCUMENTS_PER_BATCH} per upload)",
        )

    results = []
    for file in files:
        contents = await file.read()
        _validate_file(file.filename or "untitled", file.content_type or "", len(contents))

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
        results.append(doc)

    return results


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


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await service.delete_document(db, current_user.org_id, document_id)
