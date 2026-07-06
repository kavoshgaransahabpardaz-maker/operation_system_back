"""
Trade Intelligence — deduplication.

Hash-based exact dedup + PostgreSQL full-text similarity for near-duplicates.
"""
from __future__ import annotations

import hashlib
import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def compute_content_hash(title: str, body: str) -> str:
    """SHA-256 of normalized(title + body[:500])."""
    text_val = (title.lower().strip() + body[:500].lower().strip())
    return hashlib.sha256(text_val.encode("utf-8", errors="replace")).hexdigest()


async def is_duplicate(
    content_hash: str,
    db: AsyncSession,
    exclude_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """
    Check if an article with this content_hash_semantic already exists.
    Returns (is_dup, existing_article_id).

    exclude_id: the ID of the article being checked — must be excluded so
    an article is never considered a duplicate of itself (autoflush would
    otherwise flush the hash to the DB before this SELECT runs).
    """
    from app.modules.intel.models import IntelArticle

    query = select(IntelArticle.id).where(IntelArticle.content_hash_semantic == content_hash)
    if exclude_id is not None:
        query = query.where(IntelArticle.id != exclude_id)

    result = await db.execute(query)
    existing_id = result.scalar_one_or_none()
    if existing_id:
        return True, str(existing_id)
    return False, None


async def find_near_duplicates(title: str, db: AsyncSession) -> list[str]:
    """
    PostgreSQL full-text similarity search on title.
    Uses pg_trgm similarity if available, otherwise ILIKE.
    Returns list of article IDs with similar titles (threshold 0.8).
    """
    from app.modules.intel.models import IntelArticle

    if not title or len(title) < 10:
        return []

    # Try pg_trgm similarity first
    try:
        trgm_sql = text(
            """
            SELECT id FROM intel_articles
            WHERE similarity(title, :title) >= 0.8
            LIMIT 10
            """
        )
        result = await db.execute(trgm_sql, {"title": title})
        rows = result.fetchall()
        if rows:
            return [str(row[0]) for row in rows]
    except Exception:
        # pg_trgm not available — fall back to ILIKE
        pass

    # ILIKE fallback: match articles containing at least 70% of the title words
    try:
        words = [w for w in title.lower().split() if len(w) > 4]
        if not words:
            return []

        # Use first 3 significant words for ILIKE
        pattern = f"%{' '.join(words[:3])}%"
        result = await db.execute(
            select(IntelArticle.id).where(
                IntelArticle.title.ilike(pattern)
            ).limit(10)
        )
        return [str(row[0]) for row in result.fetchall()]
    except Exception as exc:
        logger.warning("find_near_duplicates fallback failed: %s", exc)
        return []
