import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import asc, case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.flags.models import Flag, FlagSeverity, FlagStatus
from app.modules.flags.schemas import FlagOut, FlagResolveRequest
from app.modules.flags import service
from app.modules.mismatch.suggestions import Suggestion, generate_suggestions
from app.modules.user_management.models import User

router = APIRouter(tags=["Flags"])


class SuggestionOut(BaseModel):
    field_name: str
    suggested_value: str
    cited_document_ids: list[str]
    rationale: str

# Severity sort order: critical=0, warning=1, info=2
_SEVERITY_ORDER = case(
    (Flag.severity == FlagSeverity.CRITICAL, 0),
    (Flag.severity == FlagSeverity.WARNING, 1),
    else_=2,
)


@router.get("/shipments/{shipment_id}/flags", response_model=list[FlagOut])
async def list_flags(
    shipment_id: uuid.UUID,
    status: FlagStatus | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    query = select(Flag).where(Flag.shipment_id == shipment_id)
    if status is not None:
        query = query.where(Flag.status == status)
    query = query.order_by(asc(_SEVERITY_ORDER), asc(Flag.created_at))
    result = await db.execute(query)
    return list(result.scalars())


@router.post("/flags/{flag_id}/resolve", response_model=FlagOut)
async def resolve_flag(
    flag_id: uuid.UUID,
    data: FlagResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.resolve_flag(
        flag_id=flag_id,
        user_id=current_user.id,
        decision=data.decision.value,
        chosen_value=data.chosen_value,
        note=data.note,
        db=db,
    )


@router.get("/flags/{flag_id}/suggestions", response_model=list[SuggestionOut])
async def get_flag_suggestions(
    flag_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return heuristic suggestions for resolving a mismatch flag."""
    from app.modules.document_classification.models import ClassificationResult
    from app.modules.field_extraction.models import ExtractedField

    flag_result = await db.execute(select(Flag).where(Flag.id == flag_id))
    flag = flag_result.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")

    # Load all extracted fields for the shipment
    fields_result = await db.execute(
        select(ExtractedField).where(ExtractedField.shipment_id == flag.shipment_id)
    )
    fields = list(fields_result.scalars())

    # Build doc_id → doc_type mapping
    doc_ids = list({str(f.document_id) for f in fields})
    doc_type_map: dict[str, str] = {}
    if doc_ids:
        cls_result = await db.execute(
            select(ClassificationResult).where(
                ClassificationResult.document_id.in_([f.document_id for f in fields])
            )
        )
        for cr in cls_result.scalars():
            doc_type_map[str(cr.document_id)] = cr.doc_type.value.upper()

    suggestions = generate_suggestions(fields, doc_type_map, flag)
    return [
        SuggestionOut(
            field_name=s.field_name,
            suggested_value=s.suggested_value,
            cited_document_ids=s.cited_document_ids,
            rationale=s.rationale,
        )
        for s in suggestions
    ]
