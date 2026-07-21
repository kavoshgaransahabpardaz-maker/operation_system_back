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
    ArticleFeedbackCreate,
    ArticleFeedbackOut,
    EventTypeCount,
    FilterOptionsOut,
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
    InterestTypeOption,
    KnowledgeRelationOut,
    MyFeedbackOut,
    NotificationPreferenceOut,
    NotificationPreferenceUpdate,
    OrgSourcePreferenceOut,
    OrgSourcePreferencePatch,
    PersonalizedSummaryOut,
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
    country: str | None = Query(None, description="ISO alpha-2 country code filter"),
    industry: str | None = Query(None, description="Industry tag filter"),
    matched_only: bool = Query(False, description="Return only articles matched to this org"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Returns articles for the feed. Filters: event_type, min_impact, country, industry.
    Ranked matched-first, then by impact_score desc, then ingested_at desc.
    """
    from app.modules.intel.models import ArticleTag

    org_id = current_user.org_id

    # Check whether this org has any interests configured
    has_interests_result = await db.execute(
        select(func.count()).select_from(UserInterest).where(UserInterest.org_id == org_id)
    )
    org_has_interests = (has_interests_result.scalar() or 0) > 0

    # IDs of articles matched to this org
    matched_ids_result = await db.execute(
        select(IntelMatch.article_id).where(IntelMatch.org_id == org_id).distinct()
    )
    matched_article_ids: set[uuid.UUID] = set(matched_ids_result.scalars())

    # Build base query
    query = (
        select(IntelArticle)
        .join(IntelEnrichment, IntelEnrichment.article_id == IntelArticle.id, isouter=True)
        .where(IntelArticle.is_duplicate == False)
    )

    if event_type:
        query = query.where(IntelEnrichment.event_type == event_type)
    if min_impact is not None:
        query = query.where(IntelEnrichment.impact_score >= min_impact)
    if country:
        query = query.where(
            IntelArticle.id.in_(
                select(ArticleTag.article_id).where(
                    ArticleTag.tag_type == "country",
                    ArticleTag.tag == country.upper(),
                )
            )
        )
    if industry:
        query = query.where(
            IntelArticle.id.in_(
                select(ArticleTag.article_id).where(
                    ArticleTag.tag_type == "industry",
                    ArticleTag.tag == industry.lower(),
                )
            )
        )

    # When org has interests: show only matched articles (unless caller says matched_only=False).
    # Fall back to all articles only when interests exist but no matches have been created yet
    # (e.g. interests were just added and background re-matching hasn't finished).
    if matched_only or (org_has_interests and matched_article_ids):
        query = query.where(IntelArticle.id.in_(matched_article_ids))

    # Order matched articles first, then by impact score (desc), then ingested_at (desc)
    query = query.order_by(
        desc(IntelArticle.id.in_(matched_article_ids)),
        desc(IntelEnrichment.impact_score),
        desc(IntelArticle.ingested_at),
    ).offset(offset).limit(limit)

    article_result = await db.execute(query)
    articles: list[IntelArticle] = list(article_result.scalars())

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
    # Validate type + format
    try:
        clean_value = UserInterestCreate.validate_interest(data.interest_type, data.value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    interest_type = data.interest_type.strip().lower()

    # Check for existing
    existing = await db.execute(
        select(UserInterest).where(
            UserInterest.org_id == current_user.org_id,
            UserInterest.interest_type == interest_type,
            UserInterest.value == clean_value,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interest already registered")

    interest = UserInterest(
        org_id=current_user.org_id,
        interest_type=interest_type,
        value=clean_value,
        is_explicit=True,
    )
    db.add(interest)
    await db.commit()
    await db.refresh(interest)

    # Retroactively match existing articles against the new interest
    from app.core.celery_app import celery_app as _celery
    _celery.send_task("tasks.rematch_org_articles", args=[str(current_user.org_id)], queue="intel_enrich")

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
# Interest type catalogue — drives frontend dropdowns
# ---------------------------------------------------------------------------

_INTEREST_TYPE_OPTIONS: list[dict] = [
    {
        "type": "country",
        "label": "Country",
        "description": "Track news affecting a specific country",
        "example": "GB",
        "format_hint": "2-letter ISO alpha-2 code (e.g. GB, US, DE, CN)",
    },
    {
        "type": "hs_chapter",
        "label": "HS Chapter",
        "description": "Track news for an entire HS chapter (2 digits)",
        "example": "72",
        "format_hint": "2-digit number (e.g. 72 = Iron and Steel)",
    },
    {
        "type": "hs_heading",
        "label": "HS Heading",
        "description": "Track news for a specific HS heading (4 digits)",
        "example": "7208",
        "format_hint": "4-digit number (e.g. 7208 = Flat-rolled products of iron)",
    },
    {
        "type": "hs_code",
        "label": "HS Code",
        "description": "Track news for a specific HS commodity code (6–10 digits)",
        "example": "720811",
        "format_hint": "6–10 digit number",
    },
    {
        "type": "party_name",
        "label": "Company / Party Name",
        "description": "Track news mentioning a specific supplier, buyer, carrier or port",
        "example": "Maersk",
        "format_hint": "Free text — the company or party name",
    },
    {
        "type": "industry",
        "label": "Industry",
        "description": "Track news for a specific industry sector",
        "example": "steel",
        "format_hint": "Free text — e.g. steel, automotive, energy, agriculture",
    },
]


@router.get("/intel/interest-types", response_model=list[InterestTypeOption])
async def list_interest_types(current_user: User = Depends(get_current_user)):
    """Return the catalogue of valid interest types with format hints for the UI."""
    return _INTEREST_TYPE_OPTIONS


# ---------------------------------------------------------------------------
# HS code autocomplete — returns distinct HS codes from extracted fields
# ---------------------------------------------------------------------------

@router.get("/intel/hs-codes/autocomplete")
async def hs_autocomplete(
    q: str = Query(..., min_length=2, description="HS code prefix (at least 2 digits)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return distinct HS codes from the org's extracted fields that start with the given prefix."""
    import re
    from app.modules.field_extraction.models import ExtractedField

    if not re.fullmatch(r"\d+", q):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="q must be digits only")

    result = await db.execute(
        select(ExtractedField.value_normalized)
        .where(
            ExtractedField.org_id == current_user.org_id,
            ExtractedField.field_name == "hs_code",
            ExtractedField.value_normalized.ilike(f"{q}%"),
        )
        .distinct()
        .limit(20)
    )
    codes = [row[0] for row in result.all() if row[0]]
    return {"results": sorted(codes)}


# ---------------------------------------------------------------------------
# Product description → HS codes (uses OpenAI)
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _PydanticBase


class _ProductToHsRequest(_PydanticBase):
    description: str


@router.post("/intel/interests/from-description")
async def interests_from_description(
    data: _ProductToHsRequest,
    current_user: User = Depends(get_current_user),
):
    """Convert a plain-language product description into suggested HS codes."""
    from openai import AsyncOpenAI
    from app.core.config import settings

    if not data.description.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="description is required")

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = (
        "You are an HS code expert. Given this product description, suggest the most likely "
        "HS heading codes (4-digit) and HS chapter codes (2-digit).\n\n"
        f"Product: {data.description.strip()}\n\n"
        "Respond ONLY with JSON in this exact format:\n"
        '{"hs_headings": ["7208", "7209"], "hs_chapters": ["72"], "rationale": "one sentence"}'
    )
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    import json
    raw = json.loads(response.choices[0].message.content)
    return {
        "hs_headings": raw.get("hs_headings", []),
        "hs_chapters": raw.get("hs_chapters", []),
        "rationale": raw.get("rationale", ""),
        "description": data.description.strip(),
    }


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
# Source preferences — users can enable/disable sources for their org
# ---------------------------------------------------------------------------

@router.get("/intel/sources/my-preferences", response_model=list[OrgSourcePreferenceOut])
async def list_source_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Return all sources with this org's preference (is_enabled).
    Sources with no preference record are implicitly enabled.
    """
    from app.modules.intel.models import OrgSourcePreference

    sources_result = await db.execute(
        select(IntelSource).order_by(asc(IntelSource.priority), asc(IntelSource.name))
    )
    sources = list(sources_result.scalars())

    prefs_result = await db.execute(
        select(OrgSourcePreference).where(OrgSourcePreference.org_id == current_user.org_id)
    )
    prefs_by_source: dict[uuid.UUID, OrgSourcePreference] = {
        p.source_id: p for p in prefs_result.scalars()
    }

    out = []
    for src in sources:
        pref = prefs_by_source.get(src.id)
        out.append(OrgSourcePreferenceOut(
            id=pref.id if pref else src.id,
            source_id=src.id,
            source_name=src.name,
            is_enabled=pref.is_enabled if pref else True,
            created_at=pref.created_at if pref else src.created_at,
        ))
    return out


@router.patch("/intel/sources/{source_id}/preference", response_model=OrgSourcePreferenceOut)
async def update_source_preference(
    source_id: uuid.UUID,
    data: OrgSourcePreferencePatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Enable or disable a news source for this org."""
    from app.modules.intel.models import OrgSourcePreference

    source_result = await db.execute(select(IntelSource).where(IntelSource.id == source_id))
    source = source_result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    pref_result = await db.execute(
        select(OrgSourcePreference).where(
            OrgSourcePreference.org_id == current_user.org_id,
            OrgSourcePreference.source_id == source_id,
        )
    )
    pref = pref_result.scalar_one_or_none()

    if pref:
        pref.is_enabled = data.is_enabled
    else:
        pref = OrgSourcePreference(
            org_id=current_user.org_id,
            source_id=source_id,
            is_enabled=data.is_enabled,
        )
        db.add(pref)

    await db.commit()
    await db.refresh(pref)
    return OrgSourcePreferenceOut(
        id=pref.id,
        source_id=pref.source_id,
        source_name=source.name,
        is_enabled=pref.is_enabled,
        created_at=pref.created_at,
    )


# ---------------------------------------------------------------------------
# Admin: Jobs
# ---------------------------------------------------------------------------

@router.get("/intel/jobs", response_model=list[IntelJobOut])
async def list_jobs(
    limit: int = Query(50, ge=1, le=1000),
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
# Filter options — countries, industries, event types, impact scale
# ---------------------------------------------------------------------------

_EVENT_TYPE_OPTIONS = [
    {"value": "tariff_change", "label": "Tariff & Duty Changes", "description": "New or changed import/export duties, anti-dumping measures, quota changes"},
    {"value": "sanctions", "label": "Sanctions", "description": "Sanctions lists, asset freezes, export controls, embargoes, denied parties"},
    {"value": "regulation", "label": "Regulation", "description": "Customs procedures, compliance requirements, licensing, product standards"},
    {"value": "trade_agreement", "label": "Trade Agreements", "description": "FTAs, bilateral deals, MoUs, WTO disputes"},
    {"value": "market_notice", "label": "Market Notice", "description": "Freight rates, port congestion, carrier announcements, commodity prices"},
    {"value": "company_news", "label": "Company News", "description": "M&A, supply agreements, restructuring in trade-relevant sectors"},
    {"value": "economic_data", "label": "Economic Data", "description": "GDP, PMI, trade statistics, fiscal policy, currency movements"},
    {"value": "supply_chain", "label": "Supply Chain", "description": "Disruptions, nearshoring, infrastructure investments affecting trade flows"},
    {"value": "geopolitical", "label": "Geopolitical", "description": "Political developments and conflicts affecting trade routes or market access"},
    {"value": "other", "label": "Other", "description": "Articles with indirect or general trade relevance"},
]

_IMPACT_SCALE = [
    {"level": 1, "label": "Informational", "description": "General background — no action needed, worth knowing"},
    {"level": 2, "label": "Monitor", "description": "Minor operational impact — worth watching for developments"},
    {"level": 3, "label": "Moderate Impact", "description": "May affect your costs or compliance procedures"},
    {"level": 4, "label": "Significant", "description": "Affects pricing, routing, or compliance for active traders — review required"},
    {"level": 5, "label": "Immediate Action", "description": "New sanction, emergency tariff, or port closure — act now"},
]


@router.get("/intel/filter-options", response_model=FilterOptionsOut)
async def get_filter_options(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Returns available filter values for the feed UI: countries, industries,
    event types with descriptions, and the full 1–5 impact scale definition.
    """
    from app.modules.intel.models import ArticleTag

    countries_result = await db.execute(
        select(ArticleTag.tag)
        .where(ArticleTag.tag_type == "country")
        .distinct()
        .order_by(ArticleTag.tag)
    )
    countries = list(countries_result.scalars())

    industries_result = await db.execute(
        select(ArticleTag.tag)
        .where(ArticleTag.tag_type == "industry")
        .distinct()
        .order_by(ArticleTag.tag)
    )
    industries = list(industries_result.scalars())

    return FilterOptionsOut(
        countries=countries,
        industries=industries,
        event_types=_EVENT_TYPE_OPTIONS,
        impact_scale=_IMPACT_SCALE,
    )


# ---------------------------------------------------------------------------
# Article feedback — like / dislike / comment
# ---------------------------------------------------------------------------

@router.post(
    "/intel/articles/{article_id}/feedback",
    response_model=ArticleFeedbackOut,
    status_code=status.HTTP_200_OK,
)
async def submit_feedback(
    article_id: uuid.UUID,
    data: ArticleFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Submit or update thumbs-up / thumbs-down feedback on an article.
    One record per user per article — re-submitting updates the existing one.
    feedback must be 'like' or 'dislike'.
    """
    from app.modules.intel.models import ArticleFeedback

    if data.feedback not in ("like", "dislike"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="feedback must be 'like' or 'dislike'")

    await _get_article_or_404(article_id, db)

    result = await db.execute(
        select(ArticleFeedback).where(
            ArticleFeedback.article_id == article_id,
            ArticleFeedback.user_id == current_user.id,
        )
    )
    fb = result.scalar_one_or_none()

    if fb:
        fb.feedback = data.feedback
        fb.comment = data.comment
    else:
        fb = ArticleFeedback(
            article_id=article_id,
            user_id=current_user.id,
            org_id=current_user.org_id,
            feedback=data.feedback,
            comment=data.comment,
        )
        db.add(fb)

    await db.commit()
    await db.refresh(fb)
    return fb


@router.get("/intel/articles/{article_id}/feedback", response_model=MyFeedbackOut)
async def get_my_feedback(
    article_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Return the current user's feedback on this article, or null values if none given."""
    from app.modules.intel.models import ArticleFeedback

    result = await db.execute(
        select(ArticleFeedback).where(
            ArticleFeedback.article_id == article_id,
            ArticleFeedback.user_id == current_user.id,
        )
    )
    fb = result.scalar_one_or_none()
    if not fb:
        return MyFeedbackOut(feedback=None, comment=None)
    return MyFeedbackOut(feedback=fb.feedback, comment=fb.comment)


@router.delete("/intel/articles/{article_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback(
    article_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Remove the current user's feedback on an article."""
    from app.modules.intel.models import ArticleFeedback

    result = await db.execute(
        select(ArticleFeedback).where(
            ArticleFeedback.article_id == article_id,
            ArticleFeedback.user_id == current_user.id,
        )
    )
    fb = result.scalar_one_or_none()
    if fb:
        await db.delete(fb)
        await db.commit()


# ---------------------------------------------------------------------------
# Personalized AI summary
# ---------------------------------------------------------------------------

@router.get("/intel/articles/{article_id}/personalized-summary", response_model=PersonalizedSummaryOut)
async def get_personalized_summary(
    article_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Generate an AI summary of this article tailored to the org's declared interests
    (HS codes, countries, industries, commodities). Computed on demand — not cached.
    """
    article = await _get_article_or_404(article_id, db)
    enrichment = await _load_enrichment(article_id, db)

    # Load org interests
    interests_result = await db.execute(
        select(UserInterest).where(UserInterest.org_id == current_user.org_id)
    )
    interests: list[UserInterest] = list(interests_result.scalars())

    interest_lines = [f"- {i.interest_type}: {i.value}" for i in interests]
    interest_block = "\n".join(interest_lines) if interest_lines else "No specific interests defined yet."

    # Identify which interests are relevant to this article
    enrichment_values: set[str] = set()
    if enrichment:
        for lst in [enrichment.countries, enrichment.hs_chapters, enrichment.hs_headings,
                    enrichment.industries, enrichment.commodities]:
            if lst:
                enrichment_values.update(str(v).upper() for v in lst)

    relevant_interests = [
        f"{i.interest_type}: {i.value}"
        for i in interests
        if i.value.upper() in enrichment_values
    ]

    general_summary = enrichment.summary if enrichment else None

    # Build prompt
    text_snippet = f"Title: {article.title}\n\n{article.content_raw[:4000]}"
    prompt = f"""You are a trade intelligence analyst. Summarise the following article in 3–4 sentences, specifically highlighting what it means for a customs broker with these interests:

{interest_block}

Focus on: tariff changes, duty rates, compliance steps, HS code implications, affected countries, and any immediate actions the broker should consider.
If the article is not directly relevant to the interests above, say so briefly but still summarise the key trade impact.

Article:
{text_snippet}

Return ONLY the summary — no preamble, no bullet points."""

    try:
        from openai import AsyncOpenAI
        from app.core.config import settings

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
        personalized = response.choices[0].message.content.strip()
    except Exception:
        personalized = general_summary or "Summary unavailable."

    return PersonalizedSummaryOut(
        article_id=article_id,
        summary=personalized,
        relevant_interests=relevant_interests,
        general_summary=general_summary,
    )


# ---------------------------------------------------------------------------
# Knowledge graph stats
# ---------------------------------------------------------------------------

@router.get("/intel/knowledge-graph/stats")
async def knowledge_graph_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Return counts and samples from the knowledge graph.
    Use this to verify the graph is populated and understand what entities it contains.
    """
    total_result = await db.execute(
        select(func.count(KnowledgeRelation.id))
    )
    total = total_result.scalar() or 0

    by_predicate_result = await db.execute(
        select(KnowledgeRelation.predicate, func.count(KnowledgeRelation.id))
        .group_by(KnowledgeRelation.predicate)
        .order_by(desc(func.count(KnowledgeRelation.id)))
    )
    by_predicate = {row[0]: row[1] for row in by_predicate_result.fetchall()}

    by_subject_type_result = await db.execute(
        select(KnowledgeRelation.subject_type, func.count(KnowledgeRelation.id))
        .group_by(KnowledgeRelation.subject_type)
        .order_by(desc(func.count(KnowledgeRelation.id)))
    )
    by_subject_type = {row[0]: row[1] for row in by_subject_type_result.fetchall()}

    return {
        "total_relations": total,
        "by_predicate": by_predicate,
        "by_subject_type": by_subject_type,
        "explanation": (
            "The knowledge graph extracts entity relationships from enriched articles. "
            "Relations include: country→commodity (affects_commodity), company→country (operates_in), "
            "sanctions→company (targets), country→trade_agreement (party_to), hs_code→country (affected_in). "
            "It is populated automatically as articles are enriched by the Celery pipeline."
        ),
    }


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
