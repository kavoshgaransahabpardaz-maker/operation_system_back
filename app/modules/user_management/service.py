import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.modules.user_management.models import Organization, PasswordResetToken, User, UserRole
from app.modules.user_management.schemas import LoginRequest, OrgCreate, UserCreate, UserRegister, UserUpdate


async def register_org_and_admin(db: AsyncSession, data: UserRegister) -> tuple[Organization, User]:
    existing_slug = await db.execute(select(Organization).where(Organization.slug == data.org_slug))
    if existing_slug.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization slug already taken")

    existing_email = await db.execute(select(User).where(User.email == data.email))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    org = Organization(name=data.org_name, slug=data.org_slug)
    db.add(org)
    await db.flush()

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        org_id=org.id,
        role=UserRole.ADMIN,
    )
    db.add(user)
    await db.commit()
    await db.refresh(org)
    await db.refresh(user)
    return org, user


async def login(db: AsyncSession, data: LoginRequest) -> str:
    result = await db.execute(select(User).where(User.email == data.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return create_access_token({"sub": str(user.id), "org_id": str(user.org_id), "role": user.role})


async def create_user(db: AsyncSession, org_id: uuid.UUID, data: UserCreate) -> User:
    existing = await db.execute(select(User).where(User.email == data.email, User.org_id == org_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered in this org")
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        org_id=org_id,
        role=data.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(db: AsyncSession, org_id: uuid.UUID) -> list[User]:
    result = await db.execute(select(User).where(User.org_id == org_id))
    return list(result.scalars().all())


async def update_user(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: UserUpdate) -> User:
    result = await db.execute(select(User).where(User.id == user_id, User.org_id == org_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)
    return user


async def request_password_reset(db: AsyncSession, email: str) -> str:
    result = await db.execute(select(User).where(User.email == email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        # Return a fake token to avoid email enumeration
        return secrets.token_urlsafe(32)

    plain_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plain_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_token)
    await db.commit()
    return plain_token


async def confirm_password_reset(db: AsyncSession, token: str, new_password: str) -> bool:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > now,
        )
    )
    reset_token = result.scalar_one_or_none()
    if not reset_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user_result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found")

    user.password_hash = hash_password(new_password)
    reset_token.used = True
    await db.commit()
    return True
