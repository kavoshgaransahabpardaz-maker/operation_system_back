import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.flags.models import Flag, FlagSeverity, FlagStatus
from app.modules.flags.schemas import FlagOut, FlagResolveRequest
from app.modules.flags import service
from app.modules.user_management.models import User

router = APIRouter(tags=["Flags"])

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
