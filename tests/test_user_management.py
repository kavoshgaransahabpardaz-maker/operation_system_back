"""Tests for Module 1: User Management (PRD §Module 1)"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_management.models import Organization, PasswordResetToken, User, UserRole
from app.modules.user_management import service
from app.modules.user_management.schemas import LoginRequest, UserRegister


# ── Registration ──────────────────────────────────────────────────────────────

async def test_register_creates_org_and_admin(client: AsyncClient):
    payload = {
        "email": "newuser@example.com",
        "password": "securepass",
        "org_name": "New Corp",
        "org_slug": f"new-corp-{uuid.uuid4().hex[:6]}",
    }
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "newuser@example.com"
    assert data["role"] == "admin"


async def test_register_duplicate_slug_fails(client: AsyncClient, test_org: Organization):
    payload = {
        "email": "another@example.com",
        "password": "pass",
        "org_name": "X",
        "org_slug": test_org.slug,  # already taken
    }
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 409


async def test_register_duplicate_email_fails(client: AsyncClient, test_user: User, test_org: Organization):
    payload = {
        "email": test_user.email,
        "password": "pass",
        "org_name": "Another Org",
        "org_slug": f"another-{uuid.uuid4().hex[:6]}",
    }
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 409


# ── Login ─────────────────────────────────────────────────────────────────────

async def test_login_success(client: AsyncClient, test_user: User):
    r = await client.post("/api/v1/auth/login", json={
        "email": test_user.email, "password": "password123"
    })
    assert r.status_code == 200
    assert "access_token" in r.json()
    assert r.json()["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient, test_user: User):
    r = await client.post("/api/v1/auth/login", json={
        "email": test_user.email, "password": "wrongpass"
    })
    assert r.status_code == 401


async def test_login_nonexistent_user(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={
        "email": "ghost@example.com", "password": "pass"
    })
    assert r.status_code == 401


# ── Current user ──────────────────────────────────────────────────────────────

async def test_get_me(client: AsyncClient, test_user: User):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == test_user.email
    assert r.json()["role"] == "admin"


# ── User management (admin) ───────────────────────────────────────────────────

async def test_list_users(client: AsyncClient, test_user: User):
    r = await client.get("/api/v1/auth/users")
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert test_user.email in emails


async def test_create_user(client: AsyncClient):
    payload = {"email": f"op-{uuid.uuid4().hex[:6]}@test.com", "password": "pass", "role": "operator"}
    r = await client.post("/api/v1/auth/users", json=payload)
    assert r.status_code == 201
    assert r.json()["role"] == "operator"


async def test_update_user_role(client: AsyncClient, operator_user: User):
    r = await client.patch(
        f"/api/v1/auth/users/{operator_user.id}",
        json={"role": "manager"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "manager"


async def test_update_user_deactivate(client: AsyncClient, operator_user: User):
    r = await client.patch(
        f"/api/v1/auth/users/{operator_user.id}",
        json={"is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False


async def test_update_nonexistent_user(client: AsyncClient):
    r = await client.patch(f"/api/v1/auth/users/{uuid.uuid4()}", json={"role": "manager"})
    assert r.status_code == 404


# ── Password reset ────────────────────────────────────────────────────────────

async def test_password_reset_request_returns_token(client: AsyncClient, test_user: User):
    r = await client.post("/api/v1/auth/password-reset", json={"email": test_user.email})
    assert r.status_code == 200
    data = r.json()
    assert "reset_token" in data
    assert len(data["reset_token"]) > 10


async def test_password_reset_unknown_email_returns_token_anyway(client: AsyncClient):
    """Should not reveal whether email exists (security: no enumeration)."""
    r = await client.post("/api/v1/auth/password-reset", json={"email": "nobody@ghost.com"})
    assert r.status_code == 200
    assert "reset_token" in r.json()


async def test_password_reset_confirm_success(client: AsyncClient, test_user: User, db: AsyncSession):
    # Request a reset token via service directly
    token = await service.request_password_reset(db, test_user.email)

    r = await client.post("/api/v1/auth/password-reset/confirm", json={
        "token": token,
        "new_password": "newpassword456",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # Verify new password works
    r2 = await client.post("/api/v1/auth/login", json={
        "email": test_user.email, "password": "newpassword456"
    })
    assert r2.status_code == 200


async def test_password_reset_invalid_token(client: AsyncClient):
    r = await client.post("/api/v1/auth/password-reset/confirm", json={
        "token": "invalid-token-xyz",
        "new_password": "newpass",
    })
    assert r.status_code == 400


async def test_password_reset_token_cannot_be_reused(client: AsyncClient, test_user: User, db: AsyncSession):
    token = await service.request_password_reset(db, test_user.email)
    await client.post("/api/v1/auth/password-reset/confirm", json={
        "token": token, "new_password": "newpass1"
    })
    # Use same token again
    r = await client.post("/api/v1/auth/password-reset/confirm", json={
        "token": token, "new_password": "newpass2"
    })
    assert r.status_code == 400


# ── RBAC ──────────────────────────────────────────────────────────────────────

async def test_operator_cannot_list_users(db: AsyncSession, operator_user: User):
    """Operators must not access admin-only endpoints."""
    from app.main import app
    from app.core.database import get_async_db
    from app.core.dependencies import get_current_user

    async def _db():
        yield db

    async def _user():
        return operator_user

    app.dependency_overrides[get_async_db] = _db
    app.dependency_overrides[get_current_user] = _user

    async with AsyncClient(
        transport=__import__("httpx").ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/auth/users")
    app.dependency_overrides.clear()

    assert r.status_code == 403
