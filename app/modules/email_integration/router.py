import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user
from app.modules.email_integration import service
from app.modules.email_integration.models import MailboxConnection
from app.modules.email_integration.schemas import (
    EmailKeywordsUpdate,
    ImapConnectionCreate,
    MailboxConnectionOut,
)
from app.modules.user_management.models import User

router = APIRouter(prefix="/email", tags=["Email Integration"])


@router.post("/connections/imap", response_model=MailboxConnectionOut, status_code=201)
async def connect_imap(
    data: ImapConnectionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    conn = await service.create_imap_connection_async(
        db=db,
        org_id=current_user.org_id,
        user_id=current_user.id,
        email_address=data.email_address,
        imap_host=data.imap_host,
        imap_port=data.imap_port,
        password=data.password,
    )
    return conn


@router.get("/connections", response_model=list[MailboxConnectionOut])
async def list_connections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(MailboxConnection).where(
            MailboxConnection.org_id == current_user.org_id,
            MailboxConnection.is_active == True,
        )
    )
    return list(result.scalars().all())


@router.post("/connections/{connection_id}/sync", status_code=202)
async def trigger_sync(
    connection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    from app.agents.email_collector.tasks import sync_mailbox
    sync_mailbox.apply_async(args=[str(connection_id)], queue="email")
    return {"status": "sync queued", "connection_id": str(connection_id)}


@router.patch("/connections/{connection_id}/keywords", response_model=MailboxConnectionOut)
async def update_keywords(
    connection_id: uuid.UUID,
    data: EmailKeywordsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    from fastapi import HTTPException as _HTTPException
    result = await db.execute(
        select(MailboxConnection).where(
            MailboxConnection.id == connection_id,
            MailboxConnection.org_id == current_user.org_id,
            MailboxConnection.is_active == True,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise _HTTPException(status_code=404, detail="Connection not found")
    conn.email_keywords = data.keywords if data.keywords else None
    await db.commit()
    await db.refresh(conn)
    return conn


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(
    connection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(MailboxConnection).where(
            MailboxConnection.id == connection_id,
            MailboxConnection.org_id == current_user.org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn:
        conn.is_active = False
        await db.commit()
