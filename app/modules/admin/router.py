"""
Super-admin panel endpoints.

All routes require SUPER_ADMIN role. They operate across all organisations
unlike the per-org admin endpoints in auth/users.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_super_admin
from app.modules.user_management.models import Organization, User, UserRole
from app.modules.user_management.schemas import (
    OrgCreate,
    OrgOut,
    OrgOutWithStats,
    OrgUpdate,
    UserOut,
    UserOutWithOrg,
    UserUpdate,
)
from app.modules.intel.models import IntelSource, IntelJob
from app.modules.intel.schemas import IntelSourceCreate, IntelSourceOut, IntelSourceUpdate, IntelJobOut

router = APIRouter(prefix="/admin", tags=["Super Admin"])


# ---------------------------------------------------------------------------
# Users (cross-org)
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserOutWithOrg])
async def list_all_users(
    is_active: bool | None = Query(None),
    role: UserRole | None = Query(None),
    org_id: uuid.UUID | None = Query(None),
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """List every user across all organisations."""
    q = select(User).options(selectinload(User.organization))
    if is_active is not None:
        q = q.where(User.is_active == is_active)
    if role is not None:
        q = q.where(User.role == role)
    if org_id is not None:
        q = q.where(User.org_id == org_id)
    result = await db.execute(q.order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        UserOutWithOrg(
            **UserOut.model_validate(u).model_dump(),
            org_name=u.organization.name,
            org_slug=u.organization.slug,
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=UserOutWithOrg)
async def update_any_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Update any user's role or active status across any org."""
    result = await db.execute(
        select(User).options(selectinload(User.organization)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id and data.role is not None and data.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Super admin cannot demote themselves",
        )
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)
    return UserOutWithOrg(
        **UserOut.model_validate(user).model_dump(),
        org_name=user.organization.name,
        org_slug=user.organization.slug,
    )


@router.delete("/users/{user_id}", status_code=204)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Deactivate (soft-delete) any user."""
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Organisations
# ---------------------------------------------------------------------------

@router.get("/organizations", response_model=list[OrgOutWithStats])
async def list_all_orgs(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Organization, func.count(User.id).label("user_count"))
        .outerjoin(User, User.org_id == Organization.id)
        .group_by(Organization.id)
        .order_by(Organization.created_at.desc())
    )
    rows = result.all()
    return [
        OrgOutWithStats(
            id=org.id,
            name=org.name,
            slug=org.slug,
            created_at=org.created_at,
            user_count=count,
        )
        for org, count in rows
    ]


@router.post("/organizations", response_model=OrgOut, status_code=201)
async def create_org(
    data: OrgCreate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    existing = await db.execute(select(Organization).where(Organization.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")
    org = Organization(name=data.name, slug=data.slug)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.patch("/organizations/{org_id}", response_model=OrgOut)
async def update_org(
    org_id: uuid.UUID,
    data: OrgUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if data.slug:
        clash = await db.execute(
            select(Organization).where(Organization.slug == data.slug, Organization.id != org_id)
        )
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")
    if data.name is not None:
        org.name = data.name
    if data.slug is not None:
        org.slug = data.slug
    await db.commit()
    await db.refresh(org)
    return org


# ---------------------------------------------------------------------------
# Intel Sources (super-admin CRUD, visible across all orgs)
# ---------------------------------------------------------------------------

@router.get("/sources", response_model=list[IntelSourceOut])
async def list_sources(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(IntelSource).order_by(IntelSource.priority.asc(), IntelSource.name))
    return list(result.scalars().all())


@router.post("/sources", response_model=IntelSourceOut, status_code=201)
async def create_source(
    data: IntelSourceCreate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    existing = await db.execute(select(IntelSource).where(IntelSource.url == data.url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source URL already exists")
    source = IntelSource(**data.model_dump(exclude_none=True))
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.patch("/sources/{source_id}", response_model=IntelSourceOut)
async def update_source(
    source_id: uuid.UUID,
    data: IntelSourceUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(IntelSource).where(IntelSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(IntelSource).where(IntelSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    source.is_active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=list[IntelJobOut])
async def list_jobs(
    status: str | None = Query(None),
    source_id: uuid.UUID | None = Query(None),
    limit: int = Query(100, le=500),
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    q = select(IntelJob).order_by(IntelJob.created_at.desc()).limit(limit)
    if status:
        q = q.where(IntelJob.status == status)
    if source_id:
        q = q.where(IntelJob.source_id == source_id)
    result = await db.execute(q)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# System analytics
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def system_analytics(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """System-wide stats snapshot."""
    from app.modules.intel.models import IntelArticle, IntelEnrichment
    from sqlalchemy import case

    org_count = (await db.execute(select(func.count()).select_from(Organization))).scalar()
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar()
    active_user_count = (await db.execute(
        select(func.count()).select_from(User).where(User.is_active == True)
    )).scalar()
    source_count = (await db.execute(select(func.count()).select_from(IntelSource))).scalar()
    active_source_count = (await db.execute(
        select(func.count()).select_from(IntelSource).where(IntelSource.is_active == True)
    )).scalar()
    article_count = (await db.execute(select(func.count()).select_from(IntelArticle))).scalar()
    enriched_count = (await db.execute(select(func.count()).select_from(IntelEnrichment))).scalar()
    job_count = (await db.execute(select(func.count()).select_from(IntelJob))).scalar()
    failed_job_count = (await db.execute(
        select(func.count()).select_from(IntelJob).where(IntelJob.status == "failed")
    )).scalar()

    # Role breakdown
    role_rows = (await db.execute(
        select(User.role, func.count(User.id)).group_by(User.role)
    )).all()
    role_breakdown = {str(r): c for r, c in role_rows}

    return {
        "organizations": {"total": org_count},
        "users": {
            "total": user_count,
            "active": active_user_count,
            "by_role": role_breakdown,
        },
        "intel_sources": {
            "total": source_count,
            "active": active_source_count,
        },
        "intel_articles": {
            "total": article_count,
            "enriched": enriched_count,
        },
        "intel_jobs": {
            "total": job_count,
            "failed": failed_job_count,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
