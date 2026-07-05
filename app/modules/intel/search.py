"""
Trade Intelligence — Full-text search using PostgreSQL FTS.

Uses to_tsvector + to_tsquery for articles.
Also searches ArticleTag for tag-based queries.

Migration note:
  CREATE INDEX IF NOT EXISTS ix_intel_articles_fts
  ON intel_articles USING gin(to_tsvector('english', title || ' ' || coalesce(content_raw, '')));
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MAX_RESULTS = 200


async def search_articles(
    query: str,
    limit: int,
    db: AsyncSession,
    filters: dict | None = None,
) -> list[dict]:
    """
    PostgreSQL full-text search over article title + content_raw.
    Also searches article tags.
    Merges and deduplicates results.

    Returns list of dicts with article metadata.
    """
    if not query or not query.strip():
        return []

    filters = filters or {}
    results: dict[str, dict] = {}  # article_id → result dict

    # ------------------------------------------------------------------
    # FTS search on articles
    # ------------------------------------------------------------------
    try:
        fts_sql = text(
            """
            SELECT
                ia.id,
                ia.title,
                ia.url,
                ia.published_at,
                ia.ingested_at,
                ia.processing_status,
                ts_rank(
                    to_tsvector('english', ia.title || ' ' || coalesce(ia.content_raw, '')),
                    plainto_tsquery('english', :query)
                ) AS rank
            FROM intel_articles ia
            WHERE
                to_tsvector('english', ia.title || ' ' || coalesce(ia.content_raw, ''))
                @@ plainto_tsquery('english', :query)
                AND ia.is_duplicate = false
            ORDER BY rank DESC
            LIMIT :lim
            """
        )
        fts_result = await db.execute(fts_sql, {"query": query, "lim": min(limit, _MAX_RESULTS)})
        for row in fts_result.fetchall():
            article_id = str(row[0])
            results[article_id] = {
                "article_id": article_id,
                "title": row[1],
                "url": row[2],
                "published_at": row[3].isoformat() if row[3] else None,
                "ingested_at": row[4].isoformat() if row[4] else None,
                "processing_status": row[5],
                "rank": float(row[6]),
                "match_source": "fts",
            }
    except Exception as exc:
        logger.warning("FTS search failed, falling back to ILIKE: %s", exc)
        # ILIKE fallback
        from app.modules.intel.models import IntelArticle
        pattern = f"%{query}%"
        ilike_result = await db.execute(
            select(IntelArticle)
            .where(
                (IntelArticle.title.ilike(pattern)) | (IntelArticle.content_raw.ilike(pattern)),
                IntelArticle.is_duplicate == False,
            )
            .limit(limit)
        )
        for article in ilike_result.scalars():
            article_id = str(article.id)
            results[article_id] = {
                "article_id": article_id,
                "title": article.title,
                "url": article.url,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "ingested_at": article.ingested_at.isoformat() if article.ingested_at else None,
                "processing_status": article.processing_status,
                "rank": 0.5,
                "match_source": "ilike",
            }

    # ------------------------------------------------------------------
    # Tag search
    # ------------------------------------------------------------------
    try:
        from app.modules.intel.models import ArticleTag, IntelArticle

        tag_result = await db.execute(
            select(ArticleTag.article_id, ArticleTag.tag, ArticleTag.tag_type)
            .where(ArticleTag.tag.ilike(f"%{query}%"))
            .distinct()
            .limit(min(limit, _MAX_RESULTS))
        )
        tag_rows = tag_result.fetchall()

        tag_article_ids = [row[0] for row in tag_rows if str(row[0]) not in results]
        if tag_article_ids:
            articles_result = await db.execute(
                select(IntelArticle).where(
                    IntelArticle.id.in_(tag_article_ids),
                    IntelArticle.is_duplicate == False,
                )
            )
            for article in articles_result.scalars():
                article_id = str(article.id)
                if article_id not in results:
                    results[article_id] = {
                        "article_id": article_id,
                        "title": article.title,
                        "url": article.url,
                        "published_at": article.published_at.isoformat() if article.published_at else None,
                        "ingested_at": article.ingested_at.isoformat() if article.ingested_at else None,
                        "processing_status": article.processing_status,
                        "rank": 0.3,
                        "match_source": "tag",
                    }
    except Exception as exc:
        logger.warning("Tag search failed: %s", exc)

    # Apply filters
    event_type_filter = filters.get("event_type")
    if event_type_filter:
        # Filter by enrichment event_type — requires a follow-up DB call
        # For simplicity we return all and let caller filter
        pass

    # Sort by rank DESC
    sorted_results = sorted(results.values(), key=lambda x: -x["rank"])
    return sorted_results[:limit]


async def suggest_search_terms(prefix: str, db: AsyncSession) -> list[str]:
    """
    Return up to 10 tags that start with prefix (for autocomplete).
    Queries ArticleTag.tag ILIKE prefix%.
    """
    if not prefix or len(prefix) < 2:
        return []

    from app.modules.intel.models import ArticleTag

    result = await db.execute(
        select(ArticleTag.tag)
        .where(ArticleTag.tag.ilike(f"{prefix}%"))
        .distinct()
        .limit(10)
    )
    return [row[0] for row in result.fetchall()]
