"""
Trade Intelligence — Knowledge Graph (PostgreSQL-backed).

Extracts KnowledgeRelation rows from enrichment results and provides
graph traversal helpers.  All operations are async + pure SQL — no LLM.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def extract_relations(
    enrichment,  # EnrichmentResult instance
    article_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Extract KnowledgeRelation rows from enrichment.

    Relation patterns created:
    - country + commodity → country 'affects_commodity' commodity
    - company + country   → company 'operates_in' country
    - sanctions articles  → regulation 'targets' company
    - country + trade_agreement → country 'party_to' trade_agreement
    - hs_code + country   → hs_code 'imported_by' / 'exported_by' country

    Skips if identical relation already exists.
    """
    from app.modules.intel.models import KnowledgeRelation

    relations_to_add: list[dict] = []

    affected_countries = list(enrichment.affected_countries or [])
    all_countries = list(set((enrichment.countries or []) + affected_countries))
    commodities = list(enrichment.commodities or [])
    companies = list(enrichment.companies or [])
    trade_agreements = list(enrichment.trade_agreements or [])
    hs_chapters = list(enrichment.hs_chapters or [])

    # country × commodity
    for country in affected_countries:
        for commodity in commodities:
            relations_to_add.append({
                "subject_type": "country",
                "subject_value": country,
                "predicate": "affects_commodity",
                "object_type": "commodity",
                "object_value": commodity,
                "confidence": 0.8,
            })

    # company × country
    for company in companies:
        for country in all_countries:
            relations_to_add.append({
                "subject_type": "company",
                "subject_value": company,
                "predicate": "operates_in",
                "object_type": "country",
                "object_value": country,
                "confidence": 0.7,
            })

    # sanctions: regulation → company
    if enrichment.event_type == "sanctions":
        for company in companies:
            relations_to_add.append({
                "subject_type": "regulation",
                "subject_value": "sanctions",
                "predicate": "targets",
                "object_type": "company",
                "object_value": company,
                "confidence": 0.95,
            })

    # trade agreement × country
    for ta in trade_agreements:
        for country in all_countries:
            relations_to_add.append({
                "subject_type": "country",
                "subject_value": country,
                "predicate": "party_to",
                "object_type": "trade_agreement",
                "object_value": ta,
                "confidence": 0.85,
            })

    # HS code × affected country
    for hs in hs_chapters:
        for country in affected_countries:
            relations_to_add.append({
                "subject_type": "hs_code",
                "subject_value": hs,
                "predicate": "affected_in",
                "object_type": "country",
                "object_value": country,
                "confidence": 0.75,
            })

    # Deduplicate and persist
    for rel in relations_to_add:
        if not rel["subject_value"] or not rel["object_value"]:
            continue

        # Check for existing identical relation
        existing = await db.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.subject_type == rel["subject_type"],
                KnowledgeRelation.subject_value == rel["subject_value"],
                KnowledgeRelation.predicate == rel["predicate"],
                KnowledgeRelation.object_type == rel["object_type"],
                KnowledgeRelation.object_value == rel["object_value"],
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            continue

        db.add(KnowledgeRelation(
            subject_type=rel["subject_type"],
            subject_value=rel["subject_value"],
            predicate=rel["predicate"],
            object_type=rel["object_type"],
            object_value=rel["object_value"],
            article_id=article_id,
            confidence=rel["confidence"],
        ))

    # Don't commit here — caller manages the transaction


async def get_related_articles(
    subject_type: str,
    subject_value: str,
    db: AsyncSession,
) -> list[dict]:
    """
    Find articles related to a given entity via KnowledgeRelation.
    Returns list of dicts with article_id + relation info.
    """
    from app.modules.intel.models import KnowledgeRelation

    result = await db.execute(
        select(KnowledgeRelation).where(
            KnowledgeRelation.subject_type == subject_type,
            KnowledgeRelation.subject_value == subject_value,
            KnowledgeRelation.article_id.is_not(None),
        ).order_by(KnowledgeRelation.confidence.desc()).limit(50)
    )
    relations = list(result.scalars())

    return [
        {
            "article_id": str(r.article_id),
            "predicate": r.predicate,
            "object_type": r.object_type,
            "object_value": r.object_value,
            "confidence": r.confidence,
        }
        for r in relations
    ]


async def get_relations_for_subject(
    subject_type: str,
    subject_value: str,
    db: AsyncSession,
) -> list[dict]:
    """
    Return all KnowledgeRelation rows for a subject.
    """
    from app.modules.intel.models import KnowledgeRelation

    result = await db.execute(
        select(KnowledgeRelation).where(
            KnowledgeRelation.subject_type == subject_type,
            KnowledgeRelation.subject_value == subject_value,
        ).order_by(KnowledgeRelation.confidence.desc()).limit(200)
    )
    relations = list(result.scalars())

    return [
        {
            "id": str(r.id),
            "subject_type": r.subject_type,
            "subject_value": r.subject_value,
            "predicate": r.predicate,
            "object_type": r.object_type,
            "object_value": r.object_value,
            "article_id": str(r.article_id) if r.article_id else None,
            "confidence": r.confidence,
            "created_at": r.created_at.isoformat(),
        }
        for r in relations
    ]


async def update_trending_topics(db: AsyncSession) -> None:
    """
    Aggregate ArticleTag counts for last 7 days → upsert TrendingTopic rows.
    Designed to run daily via Celery beat.
    """
    from app.modules.intel.models import ArticleTag, TrendingTopic, IntelArticle

    period_end = datetime.now(timezone.utc).date()
    period_start = (datetime.now(timezone.utc) - timedelta(days=7)).date()

    # Count tags by (tag, tag_type) for articles in the period
    count_sql = text(
        """
        SELECT at.tag, at.tag_type, COUNT(DISTINCT at.article_id) AS article_count
        FROM article_tags at
        JOIN intel_articles ia ON ia.id = at.article_id
        WHERE ia.ingested_at >= :period_start
          AND ia.ingested_at < :period_end_exclusive
        GROUP BY at.tag, at.tag_type
        ORDER BY article_count DESC
        LIMIT 500
        """
    )

    result = await db.execute(
        count_sql,
        {
            "period_start": datetime.combine(period_start, datetime.min.time()),
            "period_end_exclusive": datetime.combine(period_end, datetime.min.time()) + timedelta(days=1),
        },
    )
    rows = result.fetchall()

    inserted = 0
    for row in rows:
        tag, tag_type, article_count = row

        # Check if exists for same period
        existing = await db.execute(
            select(TrendingTopic).where(
                TrendingTopic.topic == tag,
                TrendingTopic.topic_type == tag_type,
                TrendingTopic.period_start == period_start,
                TrendingTopic.period_end == period_end,
            ).limit(1)
        )
        existing_row = existing.scalar_one_or_none()

        if existing_row:
            existing_row.article_count = article_count
        else:
            db.add(TrendingTopic(
                topic=tag,
                topic_type=tag_type,
                article_count=article_count,
                period_start=period_start,
                period_end=period_end,
            ))
            inserted += 1

    await db.commit()
    logger.info(
        "update_trending_topics: upserted %d trending topics for period %s–%s",
        inserted, period_start, period_end,
    )
