"""
Trade Intelligence — Recommendation Engine.

Deterministic relevance scoring — no LLM, no network.
Scores articles for orgs based on HS code, country, industry, company matches.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Score weights
_HS_WEIGHT = 0.4
_COUNTRY_WEIGHT = 0.3
_INDUSTRY_WEIGHT = 0.2
_COMPANY_WEIGHT = 0.1

# Fuzzy match threshold (rapidfuzz ratio)
_FUZZY_THRESHOLD = 80.0


async def score_article_for_org(
    article_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession,
) -> float:
    """
    Score 0.0–1.0 how relevant this article is for the org.

    Factors (all deterministic):
    1. HS code match (article tags ∩ org user_interests where type=hs_chapter/heading): +0.4
    2. Country match (article countries ∩ org interests where type=country): +0.3
    3. Industry match: +0.2
    4. Company/party name match (fuzzy): +0.1
    5. Multiply by (impact_score/5) from enrichment.

    Returns final weighted score in [0.0, 1.0].
    """
    from app.modules.intel.models import ArticleTag, UserInterest, IntelEnrichment

    # Load article tags
    tags_result = await db.execute(
        select(ArticleTag).where(ArticleTag.article_id == article_id)
    )
    tags = list(tags_result.scalars())

    # Load org interests
    interests_result = await db.execute(
        select(UserInterest).where(UserInterest.org_id == org_id)
    )
    interests = list(interests_result.scalars())

    if not tags and not interests:
        return 0.0

    # Build sets per type
    article_hs = {t.tag.lower() for t in tags if t.tag_type in ("hs_code",)}
    article_countries = {t.tag.upper() for t in tags if t.tag_type == "country"}
    article_industries = {t.tag.lower() for t in tags if t.tag_type == "industry"}
    article_companies = {t.tag for t in tags if t.tag_type == "company"}

    org_hs = {i.value.lower() for i in interests if i.interest_type in ("hs_chapter", "hs_heading", "hs_code")}
    org_countries = {i.value.upper() for i in interests if i.interest_type == "country"}
    org_industries = {i.value.lower() for i in interests if i.interest_type == "industry"}
    org_parties = {i.value for i in interests if i.interest_type == "party_name"}

    score = 0.0

    # 1. HS code match — prefix-aware: "72" matches "720811" and vice versa
    hs_match = any(
        any(art.startswith(org) or org.startswith(art) for art in article_hs)
        for org in org_hs
    )
    if hs_match:
        score += _HS_WEIGHT

    # 2. Country match
    if article_countries & org_countries:
        score += _COUNTRY_WEIGHT

    # 3. Industry match
    if article_industries & org_industries:
        score += _INDUSTRY_WEIGHT

    # 4. Company/party fuzzy match
    if article_companies and org_parties:
        try:
            from rapidfuzz import fuzz
            for company in article_companies:
                for party in org_parties:
                    if fuzz.ratio(company.lower(), party.lower()) >= _FUZZY_THRESHOLD:
                        score += _COMPANY_WEIGHT
                        break
                else:
                    continue
                break
        except ImportError:
            # rapidfuzz not available — exact match only
            if article_companies & org_parties:
                score += _COMPANY_WEIGHT

    # 5. Weight by enrichment impact score
    enrich_result = await db.execute(
        select(IntelEnrichment).where(IntelEnrichment.article_id == article_id)
    )
    enrichment = enrich_result.scalar_one_or_none()
    if enrichment and enrichment.impact_score:
        score *= (enrichment.impact_score / 5.0)

    return round(min(score, 1.0), 4)


async def get_personalized_feed(
    org_id: uuid.UUID,
    limit: int,
    offset: int,
    filters: dict,
    db: AsyncSession,
) -> list[dict]:
    """
    1. Get all enriched articles from last 30 days.
    2. Score each for the org.
    3. Sort by score DESC, then published_at DESC.
    4. Apply filters (event_type, min_impact).
    5. Return paginated results.

    Returns list of dicts with article + score.
    """
    from app.modules.intel.models import IntelArticle, IntelEnrichment

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Build query — join enrichment for filtering
    query = (
        select(IntelArticle, IntelEnrichment)
        .join(IntelEnrichment, IntelEnrichment.article_id == IntelArticle.id, isouter=True)
        .where(IntelArticle.ingested_at >= cutoff)
        .where(IntelArticle.is_duplicate == False)
    )

    # Apply filters
    event_type = filters.get("event_type")
    if event_type:
        query = query.where(IntelEnrichment.event_type == event_type)

    min_impact = filters.get("min_impact")
    if min_impact is not None:
        query = query.where(IntelEnrichment.impact_score >= int(min_impact))

    result = await db.execute(query)
    rows = result.fetchall()

    # Score each article
    scored: list[tuple[float, IntelArticle, IntelEnrichment | None]] = []
    for article, enrichment in rows:
        score = await score_article_for_org(article.id, org_id, db)
        scored.append((score, article, enrichment))

    # Sort by score DESC, published_at DESC
    scored.sort(
        key=lambda x: (
            -x[0],
            -(x[1].published_at.timestamp() if x[1].published_at else 0),
        )
    )

    # Paginate
    paginated = scored[offset: offset + limit]

    return [
        {
            "article_id": str(item[1].id),
            "score": item[0],
            "title": item[1].title,
            "url": item[1].url,
            "published_at": item[1].published_at.isoformat() if item[1].published_at else None,
            "event_type": item[2].event_type if item[2] else None,
            "impact_score": item[2].impact_score if item[2] else None,
        }
        for item in paginated
    ]
