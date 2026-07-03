from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_admin
from app.models.activity_log import ActivityAction, ActivityLog
from app.modules.org_settings import service
from app.modules.org_settings.schemas import OrgSettingsOut, OrgSettingsPatch
from app.modules.user_management.models import User

router = APIRouter(prefix="/org/settings", tags=["Org Settings"])


@router.get("", response_model=OrgSettingsOut)
async def get_org_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.get_settings(current_user.org_id, db)


@router.patch("", response_model=OrgSettingsOut)
async def patch_org_settings(
    data: OrgSettingsPatch,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    updated = await service.upsert_settings(
        org_id=current_user.org_id,
        data=data.model_dump(exclude_none=True),
        db=db,
    )

    log_entry = ActivityLog(
        org_id=current_user.org_id,
        actor_id=current_user.id,
        action=ActivityAction.SETTINGS_UPDATED,
        details=data.model_dump(exclude_none=True),
    )
    db.add(log_entry)
    await db.commit()

    return updated
