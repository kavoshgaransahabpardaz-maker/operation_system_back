import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.document_classification import service
from app.modules.document_classification.models import ClassificationResult
from app.modules.document_classification.schemas import ClassificationOut, ClassificationOverride
from app.modules.user_management.models import User

router = APIRouter(prefix="/classifications", tags=["Classification"])


@router.get("/{document_id}", response_model=ClassificationOut)
async def get_classification(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(ClassificationResult).where(ClassificationResult.document_id == document_id)
    )
    classification = result.scalar_one_or_none()
    if not classification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Classification not found")
    return classification


@router.post("/{document_id}/override", response_model=ClassificationOut)
async def override_classification(
    document_id: uuid.UUID,
    data: ClassificationOverride,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await service.override_classification_async(db, document_id, data.doc_type, current_user.id)
    # Trigger re-matching after manual override
    from app.agents.shipment_matcher.tasks import run_shipment_matching
    run_shipment_matching.apply_async(args=[str(document_id)], queue="matching")
    return result
