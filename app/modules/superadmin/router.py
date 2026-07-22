"""
Super-admin authentication — completely separate from the main Google-OAuth flow.

POST /sa/auth/login  — accepts email + password, validates SUPER_ADMIN role,
                       returns a JWT (same shape as regular tokens).
GET  /sa/auth/me     — returns the authenticated super admin's profile.

Regular users cannot reach these endpoints. The token produced here is a
standard JWT that is accepted by all /admin/* routes (which already enforce
require_super_admin), but it is stored separately in the browser
(sa_access_token) so the two sessions never overlap.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.security import create_access_token, verify_password
from app.core.dependencies import get_current_user
from app.modules.user_management.models import User, UserRole

router = APIRouter(prefix="/sa", tags=["Super Admin Auth"])


class SaLoginRequest(BaseModel):
    username: str   # the super-admin's email address
    password: str


class SaTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SaUserOut(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


@router.post("/auth/login", response_model=SaTokenResponse)
async def sa_login(
    data: SaLoginRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Authenticate a super-admin with email + password.
    Returns 403 for any non-SUPER_ADMIN account even if credentials are correct.
    """
    result = await db.execute(
        select(User).where(User.email == data.username, User.is_active == True)
    )
    user: User | None = result.scalar_one_or_none()

    # Deliberately vague error to avoid account enumeration
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )

    if not user:
        raise _invalid
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This login is restricted to super-admin accounts",
        )
    if not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has no password. Set one via the server CLI first.",
        )
    if not verify_password(data.password, user.password_hash):
        raise _invalid

    token = create_access_token({
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": user.role,
    })
    return SaTokenResponse(access_token=token)


@router.get("/auth/me", response_model=SaUserOut)
async def sa_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated super-admin's profile."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is restricted to super-admin accounts",
        )
    return SaUserOut(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.role.value,
        is_active=current_user.is_active,
    )
