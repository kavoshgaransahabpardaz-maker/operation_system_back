import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.modules.user_management.models import UserRole


class OrgCreate(BaseModel):
    name: str
    slug: str


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    org_name: str
    org_slug: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: UserRole = UserRole.OPERATOR


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    org_id: uuid.UUID
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
