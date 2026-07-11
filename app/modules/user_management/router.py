import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_admin
from app.modules.user_management import service
from app.modules.user_management.models import User
from app.modules.user_management.schemas import (
    GoogleAuthRequest,
    GoogleRegisterRequest,
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["Auth & Users"])


# ---------------------------------------------------------------------------
# Google OAuth (primary login path)
# ---------------------------------------------------------------------------

@router.post("/google", response_model=TokenResponse)
async def google_login(data: GoogleAuthRequest, db: AsyncSession = Depends(get_async_db)):
    """Sign in with a Google ID token. Returns a JWT for subsequent API calls."""
    token = await service.google_login(db, data.credential)
    return TokenResponse(access_token=token)


@router.post("/register-with-google", response_model=UserOut, status_code=201)
async def register_with_google(data: GoogleRegisterRequest, db: AsyncSession = Depends(get_async_db)):
    """Create a new organisation and admin account using a Google ID token."""
    _, user = await service.google_register_org(db, data.credential, data.org_name, data.org_slug)
    return user


# ---------------------------------------------------------------------------
# Legacy password-based endpoints (kept for backwards compat / admin access)
# ---------------------------------------------------------------------------

@router.post("/register", response_model=UserOut, status_code=201)
async def register(data: LoginRequest, db: AsyncSession = Depends(get_async_db)):
    """Deprecated — use /register-with-google instead."""
    from app.modules.user_management.schemas import UserRegister
    raise NotImplementedError("Use /auth/register-with-google")


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_async_db)):
    """Legacy password login — kept for existing accounts that still have a password_hash."""
    token = await service.login(db, data)
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

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
    """Invite a user by email. They sign in via Google using this email address."""
    return await service.create_user(db, current_user.org_id, data)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    return await service.update_user(db, current_user.org_id, user_id, data)
