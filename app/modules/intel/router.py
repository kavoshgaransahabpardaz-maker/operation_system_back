"""
Trade Intelligence — API router.

All routes under /api/v1/intel
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_admin
from app.modules.intel.models import (
    AlertDelivery,
    IntelArticle,
    IntelEnrichment,
    IntelMatch,
    IntelSource,
    UserInterest,
)
from app.modules.intel.schemas import (
    AlertDeliveryOut,
    IntelArticleOut,
    IntelEnrichmentOut,
    IntelFeedItem,
    IntelMatchOut,
    IntelSourceOut,
    UserInterestCreate,
    UserInterestOut,
)
from app.modules.user_management.models import User

router = APIRouter(tags=["Trade Intelligence"])


# ---------------------------------------------------------------------------
# Feed — matched articles for current user's org, matched-first
# ---------------------------------------------------------------------------

@router.get("/intel/feed", response_model=list[IntelFeedItem])
async def intel_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    event_type: str | None = Query(None),
    min_impact: int | None = Query(None, ge=1, le=5),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Returns articles matched to the current user's org, ranked matched-first,
    then by impact_score desc, then ingested_at desc.
    """
    org_id = current_user.org_id

    # IDs of articles that have matches for this org
    matched_ids_result = await db.execute(
        select(IntelMatch.article_id).where(IntelMatch.org_id == org_id).distinct()
    )
    matched_article_ids: set[uuid.UUID] = set(matched_ids_result.scalars())

    # Build base article query joined with enrichment filters
    query = (
        select(IntelArticle)
        .join(IntelEnrichment, IntelEnrichment.article_id == IntelArticle.id, isouter=True)
        .order_by(desc(IntelArticle.ingested_at))
        .offset(offset)
        .limit(limit)
    )

    if event_type:
        query = query.where(IntelEnrichment.event_type == event_type)
    if min_impact is not None:
        query = query.where(IntelEnrichment.impact_score >= min_impact)

    article_result = await db.execute(query)
    articles: list[IntelArticle] = list(article_result.scalars())

    # Sort: matched articles first
    articles.sort(key=lambda a: (0 if a.id in matched_article_ids else 1, ))

    feed_items: list[IntelFeedItem] = []
    for article in articles:
        enrichment = await _load_enrichment(article.id, db)
        matches = await _load_matches_for_org(article.id, org_id, db)
        first_reason = matches[0].match_reason if matches else None
        feed_items.append(
            IntelFeedItem(
                article=IntelArticleOut.model_validate(article),
                enrichment=IntelEnrichmentOut.model_validate(enrichment) if enrichment else None,
                matches=[IntelMatchOut.model_validate(m) for m in matches],
                match_reason=first_reason,
            )
        )

    return feed_items


# ---------------------------------------------------------------------------
# Search — keyword search over articles
# ---------------------------------------------------------------------------

@router.get("/intel/search", response_model=list[IntelFeedItem])
async def intel_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Keyword search over article title + content_raw (ILIKE)."""
    org_id = current_user.org_id
    pattern = f"%{q}%"

    result = await db.execute(
        select(IntelArticle)
        .where(
            (IntelArticle.title.ilike(pattern)) | (IntelArticle.content_raw.ilike(pattern))
        )
        .order_by(desc(IntelArticle.ingested_at))
        .limit(limit)
    )
    articles: list[IntelArticle] = list(result.scalars())

    feed_items: list[IntelFeedItem] = []
    for article in articles:
        enrichment = await _load_enrichment(article.id, db)
        matches = await _load_matches_for_org(article.id, org_id, db)
        first_reason = matches[0].match_reason if matches else None
        feed_items.append(
            IntelFeedItem(
                article=IntelArticleOut.model_validate(article),
                enrichment=IntelEnrichmentOut.model_validate(enrichment) if enrichment else None,
                matches=[IntelMatchOut.model_validate(m) for m in matches],
                match_reason=first_reason,
            )
        )

    return feed_items


# ---------------------------------------------------------------------------
# Single article
# ---------------------------------------------------------------------------

@router.get("/intel/articles/{article_id}", response_model=IntelFeedItem)
async def get_article(
    article_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    article = await _get_article_or_404(article_id, db)
    enrichment = await _load_enrichment(article_id, db)
    matches = await _load_matches_for_org(article_id, current_user.org_id, db)
    first_reason = matches[0].match_reason if matches else None
    return IntelFeedItem(
        article=IntelArticleOut.model_validate(article),
        enrichment=IntelEnrichmentOut.model_validate(enrichment) if enrichment else None,
        matches=[IntelMatchOut.model_validate(m) for m in matches],
        match_reason=first_reason,
    )


# ---------------------------------------------------------------------------
# Shipment intel
# ---------------------------------------------------------------------------

@router.get("/shipments/{shipment_id}/intel", response_model=list[IntelFeedItem])
async def shipment_intel(
    shipment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Articles matched to a specific shipment."""
    result = await db.execute(
        select(IntelMatch).where(IntelMatch.shipment_id == shipment_id)
    )
    matches: list[IntelMatch] = list(result.scalars())

    feed_items: list[IntelFeedItem] = []
    seen_article_ids: set[uuid.UUID] = set()
    for match in matches:
        if match.article_id in seen_article_ids:
            continue
        seen_article_ids.add(match.article_id)

        article = await _get_article_or_404(match.article_id, db)
        enrichment = await _load_enrichment(match.article_id, db)
        all_matches = await _load_matches_for_org(match.article_id, current_user.org_id, db)
        feed_items.append(
            IntelFeedItem(
                article=IntelArticleOut.model_validate(article),
                enrichment=IntelEnrichmentOut.model_validate(enrichment) if enrichment else None,
                matches=[IntelMatchOut.model_validate(m) for m in all_matches],
                match_reason=match.match_reason,
            )
        )

    return feed_items


# ---------------------------------------------------------------------------
# User interests
# ---------------------------------------------------------------------------

@router.get("/intel/interests", response_model=list[UserInterestOut])
async def list_interests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(UserInterest)
        .where(UserInterest.org_id == current_user.org_id)
        .order_by(asc(UserInterest.interest_type), asc(UserInterest.value))
    )
    return list(result.scalars())


@router.post("/intel/interests", response_model=UserInterestOut, status_code=status.HTTP_201_CREATED)
async def add_interest(
    data: UserInterestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    # Check for existing
    existing = await db.execute(
        select(UserInterest).where(
            UserInterest.org_id == current_user.org_id,
            UserInterest.interest_type == data.interest_type,
            UserInterest.value == data.value,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interest already registered",
        )

    interest = UserInterest(
        org_id=current_user.org_id,
        interest_type=data.interest_type,
        value=data.value,
        is_explicit=True,
    )
    db.add(interest)
    await db.commit()
    await db.refresh(interest)
    return interest


@router.delete("/intel/interests/{interest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interest(
    interest_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(UserInterest).where(
            UserInterest.id == interest_id,
            UserInterest.org_id == current_user.org_id,
        )
    )
    interest = result.scalar_one_or_none()
    if not interest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interest not found")
    await db.delete(interest)
    await db.commit()


# ---------------------------------------------------------------------------
# Sources (admin only)
# ---------------------------------------------------------------------------

@router.get("/intel/sources", response_model=list[IntelSourceOut])
async def list_sources(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(IntelSource).order_by(asc(IntelSource.name)))
    return list(result.scalars())


@router.post("/intel/sources/{source_id}/poll", status_code=status.HTTP_202_ACCEPTED)
async def trigger_poll(
    source_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Trigger a manual poll of a source (dispatches Celery task)."""
    result = await db.execute(select(IntelSource).where(IntelSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    from app.agents.intel_collector.tasks import poll_intel_source
    poll_intel_source.apply_async(args=[str(source_id)], queue="default")

    return {"status": "queued", "source_id": str(source_id), "source_name": source.name}


# ---------------------------------------------------------------------------
# Alert deliveries
# ---------------------------------------------------------------------------

@router.get("/intel/alerts", response_model=list[AlertDeliveryOut])
async def list_alerts(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(AlertDelivery)
        .where(AlertDelivery.org_id == current_user.org_id)
        .order_by(desc(AlertDelivery.delivered_at))
        .limit(limit)
    )
    return list(result.scalars())


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _get_article_or_404(article_id: uuid.UUID, db: AsyncSession) -> IntelArticle:
    result = await db.execute(select(IntelArticle).where(IntelArticle.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return article


async def _load_enrichment(article_id: uuid.UUID, db: AsyncSession) -> IntelEnrichment | None:
    result = await db.execute(
        select(IntelEnrichment).where(IntelEnrichment.article_id == article_id)
    )
    return result.scalar_one_or_none()


async def _load_matches_for_org(
    article_id: uuid.UUID, org_id: uuid.UUID, db: AsyncSession
) -> list[IntelMatch]:
    result = await db.execute(
        select(IntelMatch).where(
            IntelMatch.article_id == article_id,
            IntelMatch.org_id == org_id,
        )
    )
    return list(result.scalars())
