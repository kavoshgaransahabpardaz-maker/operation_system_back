import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_admin
from app.modules.user_management import service
from app.modules.user_management.models import User
from app.modules.user_management.schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserRegister,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["Auth & Users"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(data: UserRegister, db: AsyncSession = Depends(get_async_db)):
    _, user = await service.register_org_and_admin(db, data)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_async_db)):
    token = await service.login(db, data)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/users", response_model=list[UserOut])
async def list_users(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.list_users(db, current_user.org_id)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    data: UserCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.create_user(db, current_user.org_id, data)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.update_user(db, current_user.org_id, user_id, data)


class PasswordResetResponse(BaseModel):
    reset_token: str
    message: str = "In production this token would be emailed. Store it to use /password-reset/confirm."


@router.post("/password-reset", response_model=PasswordResetResponse)
async def request_password_reset(
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_async_db),
):
    token = await service.request_password_reset(db, data.email)
    return PasswordResetResponse(reset_token=token)


class PasswordResetConfirmResponse(BaseModel):
    status: str = "ok"


@router.post("/password-reset/confirm", response_model=PasswordResetConfirmResponse)
async def confirm_password_reset(
    data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_async_db),
):
    await service.confirm_password_reset(db, data.token, data.new_password)
    return PasswordResetConfirmResponse()
