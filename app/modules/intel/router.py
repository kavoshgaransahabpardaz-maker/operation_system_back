"""
Trade Intelligence — API router.

All routes under /api/v1/intel
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, desc, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import get_current_user, require_admin
from app.modules.intel.models import (
    AlertDelivery,
    ArticleTag,
    IntelArticle,
    IntelEnrichment,
    IntelJob,
    IntelMatch,
    IntelSource,
    KnowledgeRelation,
    NotificationPreference,
    TrendingTopic,
    UserInterest,
)
from app.modules.intel.schemas import (
    AlertDeliveryOut,
    EventTypeCount,
    HeatmapEntry,
    ImpactTimelineEntry,
    IntelArticleOut,
    IntelEnrichmentOut,
    IntelFeedItem,
    IntelJobOut,
    IntelMatchOut,
    IntelSourceCreate,
    IntelSourceOut,
    IntelSourceUpdate,
    KnowledgeRelationOut,
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
    SearchResult,
    TrendingTopicOut,
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
        .where(IntelArticle.is_duplicate == False)
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
# Search — full-text + tag search
# ---------------------------------------------------------------------------

@router.get("/intel/search", response_model=list[SearchResult])
async def intel_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    event_type: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Full-text search over article title + content (PostgreSQL FTS) + tags."""
    from app.modules.intel.search import search_articles

    filters = {}
    if event_type:
        filters["event_type"] = event_type

    results = await search_articles(query=q, limit=limit, db=db, filters=filters)
    return results


# ---------------------------------------------------------------------------
# Search autocomplete
# ---------------------------------------------------------------------------

@router.get("/intel/tags/autocomplete", response_model=list[str])
async def tags_autocomplete(
    prefix: str = Query(..., min_length=2),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return up to 10 tag suggestions that start with prefix."""
    from app.modules.intel.search import suggest_search_terms

    return await suggest_search_terms(prefix=prefix, db=db)


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
    """List all sources including health_status, articles_collected, last_error."""
    result = await db.execute(
        select(IntelSource).order_by(asc(IntelSource.priority), asc(IntelSource.name))
    )
    return list(result.scalars())


@router.post("/intel/sources", response_model=IntelSourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    data: IntelSourceCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new intel source (admin)."""
    existing = await db.execute(
        select(IntelSource).where(IntelSource.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source name already exists")

    source = IntelSource(
        name=data.name,
        source_type=data.source_type,
        category=data.category,
        url=data.url,
        poll_cadence_minutes=data.poll_cadence_minutes,
        is_active=data.is_active,
        priority=data.priority,
        config=data.config,
        health_status="unknown",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.patch("/intel/sources/{source_id}", response_model=IntelSourceOut)
async def update_source(
    source_id: uuid.UUID,
    data: IntelSourceUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Update an intel source (admin)."""
    result = await db.execute(select(IntelSource).where(IntelSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(source, field, value)

    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/intel/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_source(
    source_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Deactivate (soft-delete) an intel source (admin)."""
    result = await db.execute(select(IntelSource).where(IntelSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    source.is_active = False
    await db.commit()


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

    from app.agents.intel_collector.tasks import poll_source
    poll_source.apply_async(args=[str(source_id)], queue="intel_collect")

    return {"status": "queued", "source_id": str(source_id), "source_name": source.name}


# ---------------------------------------------------------------------------
# Admin: Jobs
# ---------------------------------------------------------------------------

@router.get("/intel/jobs", response_model=list[IntelJobOut])
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    job_type: str | None = Query(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """List recent IntelJob records (admin)."""
    query = select(IntelJob).order_by(desc(IntelJob.created_at)).limit(limit)
    if status_filter:
        query = query.where(IntelJob.status == status_filter)
    if job_type:
        query = query.where(IntelJob.job_type == job_type)
    result = await db.execute(query)
    return list(result.scalars())


# ---------------------------------------------------------------------------
# Admin: Re-process article
# ---------------------------------------------------------------------------

@router.post("/intel/admin/reprocess/{article_id}", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_article(
    article_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_async_db),
):
    """Re-run enrichment for a specific article (admin)."""
    article = await _get_article_or_404(article_id, db)

    from app.agents.intel_collector.tasks import enrich_article_task
    enrich_article_task.apply_async(args=[str(article_id)], queue="intel_enrich")

    return {"status": "queued", "article_id": str(article_id), "title": article.title}


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
# Notification preferences
# ---------------------------------------------------------------------------

@router.get("/intel/notifications/preferences", response_model=NotificationPreferenceOut)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Get current user's notification preferences."""
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.org_id == current_user.org_id,
            NotificationPreference.user_id == current_user.id,
        )
    )
    pref = result.scalar_one_or_none()
    if not pref:
        # Auto-create defaults
        pref = NotificationPreference(
            org_id=current_user.org_id,
            user_id=current_user.id,
        )
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return pref


@router.patch("/intel/notifications/preferences", response_model=NotificationPreferenceOut)
async def update_notification_preferences(
    data: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Update current user's notification preferences."""
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.org_id == current_user.org_id,
            NotificationPreference.user_id == current_user.id,
        )
    )
    pref = result.scalar_one_or_none()
    if not pref:
        pref = NotificationPreference(
            org_id=current_user.org_id,
            user_id=current_user.id,
        )
        db.add(pref)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(pref, field, value)

    await db.commit()
    await db.refresh(pref)
    return pref


# ---------------------------------------------------------------------------
# Analytics: Trending topics
# ---------------------------------------------------------------------------

@router.get("/intel/analytics/trending", response_model=list[TrendingTopicOut])
async def analytics_trending(
    limit: int = Query(20, ge=1, le=100),
    topic_type: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return trending topics from the last 7 days (from TrendingTopic table)."""
    query = (
        select(TrendingTopic)
        .order_by(desc(TrendingTopic.article_count))
        .limit(limit)
    )
    if topic_type:
        query = query.where(TrendingTopic.topic_type == topic_type)

    result = await db.execute(query)
    return list(result.scalars())


# ---------------------------------------------------------------------------
# Analytics: Country heatmap
# ---------------------------------------------------------------------------

@router.get("/intel/analytics/heatmap", response_model=list[HeatmapEntry])
async def analytics_heatmap(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Article count by country (from ArticleTag) over last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    sql = text(
        """
        SELECT at.tag AS country, COUNT(DISTINCT at.article_id) AS article_count
        FROM article_tags at
        JOIN intel_articles ia ON ia.id = at.article_id
        WHERE at.tag_type = 'country'
          AND ia.ingested_at >= :cutoff
        GROUP BY at.tag
        ORDER BY article_count DESC
        LIMIT 100
        """
    )
    result = await db.execute(sql, {"cutoff": cutoff})
    return [{"country": row[0], "article_count": row[1]} for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Analytics: By event type
# ---------------------------------------------------------------------------

@router.get("/intel/analytics/by-event-type", response_model=list[EventTypeCount])
async def analytics_by_event_type(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Article count by event_type over last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    sql = text(
        """
        SELECT ie.event_type, COUNT(DISTINCT ie.article_id) AS article_count
        FROM intel_enrichments ie
        JOIN intel_articles ia ON ia.id = ie.article_id
        WHERE ia.ingested_at >= :cutoff
          AND ie.event_type IS NOT NULL
        GROUP BY ie.event_type
        ORDER BY article_count DESC
        """
    )
    result = await db.execute(sql, {"cutoff": cutoff})
    return [{"event_type": row[0], "article_count": row[1]} for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Analytics: Impact timeline
# ---------------------------------------------------------------------------

@router.get("/intel/analytics/impact-timeline", response_model=list[ImpactTimelineEntry])
async def analytics_impact_timeline(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Average impact score per day over last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    sql = text(
        """
        SELECT
            DATE(ia.ingested_at) AS day,
            ROUND(AVG(ie.impact_score)::numeric, 2) AS avg_impact_score,
            COUNT(DISTINCT ia.id) AS article_count
        FROM intel_articles ia
        JOIN intel_enrichments ie ON ie.article_id = ia.id
        WHERE ia.ingested_at >= :cutoff
          AND ie.impact_score IS NOT NULL
        GROUP BY DATE(ia.ingested_at)
        ORDER BY day ASC
        """
    )
    result = await db.execute(sql, {"cutoff": cutoff})
    return [
        {
            "date": str(row[0]),
            "avg_impact_score": float(row[1]),
            "article_count": int(row[2]),
        }
        for row in result.fetchall()
    ]


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------

@router.get("/intel/knowledge-graph", response_model=list[KnowledgeRelationOut])
async def knowledge_graph(
    subject_type: str = Query(...),
    subject_value: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return knowledge graph relations for a given subject."""
    from app.modules.intel.knowledge_graph import get_relations_for_subject

    return await get_relations_for_subject(
        subject_type=subject_type,
        subject_value=subject_value,
        db=db,
    )


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
