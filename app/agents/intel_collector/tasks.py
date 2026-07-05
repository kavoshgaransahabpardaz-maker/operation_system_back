"""
Intel Collector — Celery tasks.

Tasks:
  poll_all_sources       — triggered by beat every hour; dispatches per-source tasks
  poll_intel_source      — fetch a single source, ingest new articles, queue enrichment
  enrich_and_match_article — LLM enrichment + matching + optional alert dispatch
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# poll_all_sources — Celery beat entry point
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.poll_all_sources",
    bind=True,
    max_retries=3,
    queue="default",
)
def poll_all_sources(self):
    """Triggered by Celery beat.  Dispatch poll_intel_source for every active source."""
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import select
    from app.modules.intel.models import IntelSource

    async def _load_sources() -> list[str]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(IntelSource.id).where(IntelSource.is_active == True)
            )
            return [str(sid) for sid in result.scalars()]

    try:
        source_ids = asyncio.run(_load_sources())
    except Exception as exc:
        logger.error("poll_all_sources: failed to load sources: %s", exc)
        raise self.retry(exc=exc, countdown=60)

    for source_id in source_ids:
        poll_intel_source.apply_async(args=[source_id], queue="default")
        logger.info("Queued poll for source %s", source_id)

    logger.info("poll_all_sources dispatched %d source tasks", len(source_ids))


# ---------------------------------------------------------------------------
# poll_intel_source — fetch one source
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.poll_intel_source",
    bind=True,
    max_retries=3,
    queue="default",
)
def poll_intel_source(self, source_id: str):
    """
    1. Load IntelSource.
    2. Instantiate correct adapter (RssAdapter or SanctionsAdapter).
    3. Call adapter.fetch() → list[RawArticle].
    4. For each article: compute content_hash, skip if exists, insert IntelArticle.
    5. For each new article: queue enrich_and_match_article.
    6. Update source.last_polled_at.
    """
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import IntelArticle, IntelSource
    from sqlalchemy import select
    from datetime import datetime, timezone

    src_uuid = uuid.UUID(source_id)

    async def _run() -> int:
        async with AsyncSessionLocal() as db:
            # Load source
            result = await db.execute(
                select(IntelSource).where(IntelSource.id == src_uuid)
            )
            source: IntelSource | None = result.scalar_one_or_none()
            if not source:
                logger.error("poll_intel_source: source %s not found", source_id)
                return 0

            # Instantiate adapter
            adapter = _get_adapter(source)

            # Fetch articles
            try:
                raw_articles = await adapter.fetch()
                source.last_error = None
            except Exception as exc:
                source.last_error = str(exc)
                source.last_polled_at = datetime.now(timezone.utc)
                await db.commit()
                raise

            new_count = 0
            new_article_ids: list[str] = []

            for raw in raw_articles:
                content_hash = _compute_hash(raw.title, raw.content_raw)

                # Dedup check
                dup_result = await db.execute(
                    select(IntelArticle.id).where(
                        IntelArticle.content_hash == content_hash
                    )
                )
                if dup_result.scalar_one_or_none():
                    continue  # already ingested

                article = IntelArticle(
                    source_id=source.id,
                    content_hash=content_hash,
                    url=raw.url or None,
                    title=raw.title,
                    content_raw=raw.content_raw,
                    published_at=raw.published_at,
                )
                db.add(article)
                await db.flush()  # get the generated ID
                new_article_ids.append(str(article.id))
                new_count += 1

            source.last_polled_at = datetime.now(timezone.utc)
            await db.commit()

            return new_count, new_article_ids

    try:
        new_count, new_article_ids = asyncio.run(_run())
    except Exception as exc:
        logger.error("poll_intel_source %s failed: %s", source_id, exc)
        raise self.retry(exc=exc, countdown=120)

    logger.info("poll_intel_source %s: ingested %d new articles", source_id, new_count)

    # Queue enrichment for each new article
    for article_id in new_article_ids:
        enrich_and_match_article.apply_async(args=[article_id], queue="classification")
        logger.info("Queued enrichment for article %s", article_id)


# ---------------------------------------------------------------------------
# enrich_and_match_article — LLM enrichment + matching + alerting
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.enrich_and_match_article",
    bind=True,
    max_retries=3,
    queue="classification",
)
def enrich_and_match_article(self, article_id: str):
    """
    1. Load IntelArticle.
    2. Call enrich_article() → EnrichmentResult + model_version.
    3. Call generate_embedding() → store in enrichment.
    4. Insert IntelEnrichment.
    5. Call match_article_to_shipments().
    6. If any match has impact_score >= 4: queue send_alert_task per org.
    """
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import IntelArticle, IntelEnrichment
    from app.modules.intel.enrichment import enrich_article, generate_embedding
    from app.modules.intel.matcher import match_article_to_shipments
    from app.modules.intel.alerts import send_alert
    from sqlalchemy import select

    art_uuid = uuid.UUID(article_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            # Load article
            result = await db.execute(
                select(IntelArticle).where(IntelArticle.id == art_uuid)
            )
            article: IntelArticle | None = result.scalar_one_or_none()
            if not article:
                logger.error("enrich_and_match_article: article %s not found", article_id)
                return

            # 1. Enrich
            enrichment_result, model_version = await enrich_article(article)

            # 2. Embedding
            try:
                embed_text = f"{article.title} {article.content_raw[:1000]}"
                embedding = await generate_embedding(embed_text)
            except Exception as exc:
                logger.warning("Embedding generation failed for %s: %s", article_id, exc)
                embedding = None

            # 3. Persist enrichment
            enrichment = IntelEnrichment(
                article_id=art_uuid,
                summary=enrichment_result.summary,
                event_type=enrichment_result.event_type,
                countries=enrichment_result.countries,
                hs_chapters=enrichment_result.hs_chapters,
                hs_headings=enrichment_result.hs_headings,
                regulation_refs=enrichment_result.regulation_refs,
                impact_score=enrichment_result.impact_score,
                impact_rationale=enrichment_result.impact_rationale,
                model_version=model_version,
                embedding=embedding,
            )
            db.add(enrichment)
            await db.commit()
            await db.refresh(enrichment)

            # 4. Match
            matches = await match_article_to_shipments(art_uuid, enrichment, db)

            # 5. Alert for high-impact matches (impact_score >= 4)
            if enrichment.impact_score and enrichment.impact_score >= 4 and matches:
                # Group matches by org_id
                by_org: dict[uuid.UUID, list] = {}
                for m in matches:
                    by_org.setdefault(m.org_id, []).append(m)

                for org_id, org_matches in by_org.items():
                    try:
                        await send_alert(org_id, art_uuid, org_matches, db)
                    except Exception as exc:
                        logger.error(
                            "Alert send failed for org %s article %s: %s",
                            org_id, article_id, exc,
                        )

            logger.info(
                "enrich_and_match_article %s: enriched (impact=%s), %d matches",
                article_id,
                enrichment.impact_score,
                len(matches),
            )

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("enrich_and_match_article %s failed: %s", article_id, exc)
        raise self.retry(exc=exc, countdown=60)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_hash(title: str, content: str) -> str:
    """SHA-256 of title + content."""
    payload = f"{title}\n{content}"
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def _get_adapter(source):
    """Instantiate the correct adapter based on source_type."""
    from app.modules.intel.sources.rss_adapter import RssAdapter
    from app.modules.intel.sources.sanctions_adapter import SanctionsAdapter

    if source.source_type == "sanctions_list":
        return SanctionsAdapter(source_name=source.name, list_url=source.url)
    else:
        # Default to RSS for rss / scraper / api / unknown
        return RssAdapter(url=source.url, source_name=source.name)
