import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.models.activity_log import ActivityAction
from app.models.activity_log_service import get_activity_log
from app.modules.shipment_workspace import service
from app.modules.shipment_workspace.schemas import DashboardStats, ShipmentDetail
from app.modules.user_management.models import User

router = APIRouter(prefix="/workspace", tags=["Workspace"])


class ActivityLogOut(BaseModel):
    id: uuid.UUID
    action: ActivityAction
    actor_id: uuid.UUID | None
    document_id: uuid.UUID | None
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.get_dashboard_stats(db, current_user.org_id)


@router.get("/shipments/{shipment_id}", response_model=ShipmentDetail)
async def shipment_detail(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.get_shipment_detail(db, current_user.org_id, shipment_id)


@router.get("/shipments/{shipment_id}/activity", response_model=list[ActivityLogOut])
async def shipment_activity_log(
    shipment_id: uuid.UUID,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await get_activity_log(db, current_user.org_id, shipment_id=shipment_id, limit=limit)
