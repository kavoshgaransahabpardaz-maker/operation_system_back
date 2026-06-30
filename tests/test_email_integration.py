"""Tests for Module 2: Email Integration (PRD §Module 2)"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.email_integration.models import EmailProvider, MailboxConnection
from app.modules.user_management.models import User


# ── IMAP connection ───────────────────────────────────────────────────────────

async def test_connect_imap_success(client: AsyncClient):
    r = await client.post("/api/v1/email/connections/imap", json={
        "email_address": "broker@company.com",
        "imap_host": "mail.company.com",
        "imap_port": 993,
        "password": "secret",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["email_address"] == "broker@company.com"
    assert data["provider"] == "imap"
    assert data["is_active"] is True


async def test_connect_imap_stores_encrypted_password(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    """Password must never be stored in plaintext."""
    from sqlalchemy import select
    r = await client.post("/api/v1/email/connections/imap", json={
        "email_address": "secure@test.com",
        "imap_host": "imap.test.com",
        "imap_port": 993,
        "password": "my-plain-password",
    })
    conn_id = uuid.UUID(r.json()["id"])
    result = await db.execute(select(MailboxConnection).where(MailboxConnection.id == conn_id))
    conn = result.scalar_one()
    # Stored value must not be plaintext
    assert conn.imap_password_enc != "my-plain-password"
    # Must be decryptable
    from app.core.security import decrypt_token
    assert decrypt_token(conn.imap_password_enc) == "my-plain-password"


# ── List connections ──────────────────────────────────────────────────────────

async def test_list_connections_empty(client: AsyncClient):
    r = await client.get("/api/v1/email/connections")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_list_connections_returns_active_only(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    from app.core.security import encrypt_token
    # Active connection
    active = MailboxConnection(
        org_id=test_user.org_id,
        user_id=test_user.id,
        provider=EmailProvider.IMAP,
        email_address="active@test.com",
        imap_host="imap.test.com",
        imap_port=993,
        imap_password_enc=encrypt_token("pass"),
        is_active=True,
    )
    # Inactive connection
    inactive = MailboxConnection(
        org_id=test_user.org_id,
        user_id=test_user.id,
        provider=EmailProvider.IMAP,
        email_address="inactive@test.com",
        imap_host="imap.test.com",
        imap_port=993,
        imap_password_enc=encrypt_token("pass"),
        is_active=False,
    )
    db.add(active)
    db.add(inactive)
    await db.commit()

    r = await client.get("/api/v1/email/connections")
    emails = [c["email_address"] for c in r.json()]
    assert "active@test.com" in emails
    assert "inactive@test.com" not in emails


# ── Disconnect ────────────────────────────────────────────────────────────────

async def test_disconnect_sets_inactive(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    from sqlalchemy import select
    from app.core.security import encrypt_token

    conn = MailboxConnection(
        org_id=test_user.org_id,
        user_id=test_user.id,
        provider=EmailProvider.IMAP,
        email_address="todelete@test.com",
        imap_host="imap.test.com",
        imap_port=993,
        imap_password_enc=encrypt_token("pass"),
        is_active=True,
    )
    db.add(conn)
    await db.commit()

    r = await client.delete(f"/api/v1/email/connections/{conn.id}")
    assert r.status_code == 204

    await db.refresh(conn)
    assert conn.is_active is False


async def test_disconnect_other_org_noop(client: AsyncClient, db: AsyncSession):
    """Disconnecting another org's connection should silently do nothing."""
    from app.core.security import encrypt_token

    other_conn = MailboxConnection(
        org_id=uuid.uuid4(),  # different org
        user_id=uuid.uuid4(),
        provider=EmailProvider.IMAP,
        email_address="other@test.com",
        imap_host="imap.test.com",
        imap_port=993,
        imap_password_enc=encrypt_token("pass"),
        is_active=True,
    )
    db.add(other_conn)
    await db.commit()

    r = await client.delete(f"/api/v1/email/connections/{other_conn.id}")
    assert r.status_code == 204  # no error, just a noop

    await db.refresh(other_conn)
    assert other_conn.is_active is True  # unchanged


# ── Trigger sync ──────────────────────────────────────────────────────────────

async def test_trigger_sync_queues_task(client: AsyncClient):
    connection_id = uuid.uuid4()
    r = await client.post(f"/api/v1/email/connections/{connection_id}/sync")
    assert r.status_code == 202
    assert r.json()["status"] == "sync queued"
    assert r.json()["connection_id"] == str(connection_id)


# ── Email provider enum coverage (PRD requires Gmail, M365, Outlook, IMAP) ───

def test_all_email_providers_defined():
    from app.modules.email_integration.models import EmailProvider
    required = {"gmail", "microsoft365", "outlook", "imap"}
    actual = {p.value for p in EmailProvider}
    assert required == actual
