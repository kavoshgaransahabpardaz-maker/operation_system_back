"""
Intel Collector — Celery tasks.

Full pipeline:
  poll_all_sources          — beat entry point (hourly)
  poll_source               — fetch one source, ingest raw articles
  parse_article             — parse + normalize
  deduplicate_article       — hash-based dedup
  enrich_article_task       — LLM enrichment + tags + knowledge graph
  match_article_task        — match to org shipments + score
  send_alert_task           — create AlertDelivery record
  update_trending_topics_task — daily topic aggregation
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# poll_all_sources — Celery beat entry point (hourly)
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.poll_all_sources", queue="intel_collect")
def poll_all_sources():
    """Every hour via beat.  Dispatches per-source poll tasks."""
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
        return

    for source_id in source_ids:
        poll_source.apply_async(args=[source_id], queue="intel_collect")
        logger.info("Queued poll for source %s", source_id)

    logger.info("poll_all_sources dispatched %d source tasks", len(source_ids))


# ---------------------------------------------------------------------------
# poll_source — fetch one source
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.poll_source",
    bind=True,
    max_retries=3,
    queue="intel_collect",
)
def poll_source(self, source_id: str):
    """
    1. Load source from DB.
    2. Get collector via factory.get_collector(source).
    3. Call collector.collect() → list[RawArticle].
    4. For each article: compute hash, skip if duplicate.
    5. Insert IntelArticle with status='raw'.
    6. Dispatch parse_article.delay(article_id) for each new article.
    7. Update source.last_polled_at, articles_collected.
    8. Create IntelJob record.
    """
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import IntelArticle, IntelSource, IntelJob
    from app.modules.intel.collectors.factory import get_collector
    from sqlalchemy import select

    src_uuid = uuid.UUID(source_id)

    async def _run() -> tuple[int, list[str]]:
        async with AsyncSessionLocal() as db:
            # Create job record
            job = IntelJob(
                source_id=src_uuid,
                job_type="collect",
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            db.add(job)
            await db.flush()

            # Load source
            result = await db.execute(
                select(IntelSource).where(IntelSource.id == src_uuid)
            )
            source = result.scalar_one_or_none()
            if not source:
                logger.error("poll_source: source %s not found", source_id)
                job.status = "failed"
                job.error_message = "Source not found"
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return 0, []

            # Get collector
            try:
                collector = get_collector(source)
            except ValueError as exc:
                logger.error("poll_source: unknown category for source %s: %s", source_id, exc)
                source.health_status = "unhealthy"
                source.last_error = str(exc)
                source.last_polled_at = datetime.now(timezone.utc)
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return 0, []

            # Collect articles
            try:
                raw_articles = await collector.collect()
                source.last_error = None
                source.health_status = "healthy"
            except Exception as exc:
                source.last_error = str(exc)
                source.health_status = "unhealthy"
                source.last_polled_at = datetime.now(timezone.utc)
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                raise

            new_count = 0
            new_article_ids: list[str] = []

            for raw in raw_articles:
                content_hash = _compute_hash(raw.title, raw.content_raw)

                # Dedup check (exact hash)
                dup_result = await db.execute(
                    select(IntelArticle.id).where(IntelArticle.content_hash == content_hash)
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
                    author=raw.author,
                    image_url=raw.image_url,
                    language=raw.language,
                    processing_status="raw",
                )
                db.add(article)
                await db.flush()
                new_article_ids.append(str(article.id))
                new_count += 1

            source.last_polled_at = datetime.now(timezone.utc)
            source.articles_collected = (source.articles_collected or 0) + new_count

            job.status = "completed"
            job.articles_processed = new_count
            job.completed_at = datetime.now(timezone.utc)

            await db.commit()
            return new_count, new_article_ids

    try:
        new_count, new_article_ids = asyncio.run(_run())
    except Exception as exc:
        logger.error("poll_source %s failed: %s", source_id, exc)
        raise self.retry(exc=exc, countdown=120)

    logger.info("poll_source %s: ingested %d new articles", source_id, new_count)

    for article_id in new_article_ids:
        parse_article.apply_async(args=[article_id], queue="intel_parse")
        logger.debug("Queued parse for article %s", article_id)


# ---------------------------------------------------------------------------
# parse_article — parse + normalize
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.parse_article",
    bind=True,
    max_retries=2,
    queue="intel_parse",
)
def parse_article(self, article_id: str):
    """
    1. Load article.
    2. Get parser via factory.get_parser(source_name).
    3. Parse → ParsedArticle.
    4. Normalize → standard dict.
    5. Update IntelArticle fields (language, word_count, author, etc).
    6. Set status='parsed'.
    7. Dispatch deduplicate_article.delay(article_id).
    """
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import IntelArticle, IntelSource
    from app.modules.intel.collectors.base import RawArticle as CollectorRawArticle
    from app.modules.intel.parsers.factory import get_parser
    from app.modules.intel.normalizer import normalize
    from sqlalchemy import select

    art_uuid = uuid.UUID(article_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(IntelArticle).where(IntelArticle.id == art_uuid)
            )
            article = result.scalar_one_or_none()
            if not article:
                logger.error("parse_article: article %s not found", article_id)
                return

            # Load source name
            src_result = await db.execute(
                select(IntelSource.name).where(IntelSource.id == article.source_id)
            )
            source_name = src_result.scalar_one_or_none() or ""

            # Build a RawArticle-compatible object from the DB record
            raw = CollectorRawArticle(
                url=article.url or "",
                title=article.title,
                content_raw=article.content_raw,
                published_at=article.published_at,
                author=article.author,
                language=article.language,
                image_url=article.image_url,
                source_name=source_name,
            )

            parser = get_parser(source_name)
            try:
                parsed = parser.parse(raw)
            except Exception as exc:
                logger.error("parse_article: parser error for %s: %s", article_id, exc)
                article.processing_status = "failed"
                await db.commit()
                raise

            normalized = normalize(parsed, source_name)

            # Update article fields
            article.title = normalized["title"] or article.title
            article.content_raw = normalized["body"] or article.content_raw
            article.language = normalized["language"]
            article.author = normalized["author"]
            article.image_url = normalized["image_url"]
            article.word_count = normalized["word_count"]
            if normalized["published_at"]:
                article.published_at = normalized["published_at"]
            article.processing_status = "parsed"

            await db.commit()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("parse_article %s failed: %s", article_id, exc)
        raise self.retry(exc=exc, countdown=30)

    deduplicate_article.apply_async(args=[article_id], queue="intel_parse")


# ---------------------------------------------------------------------------
# deduplicate_article
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.deduplicate_article",
    bind=True,
    queue="intel_parse",
)
def deduplicate_article(self, article_id: str):
    """
    1. Compute content_hash_semantic.
    2. Check near-duplicates via deduplicator.
    3. If duplicate: mark article.is_duplicate=True, set duplicate_of_id, status='indexed'.
    4. If unique: dispatch enrich_article_task.
    """
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import IntelArticle
    from app.modules.intel.deduplicator import compute_content_hash, is_duplicate, find_near_duplicates
    from sqlalchemy import select

    art_uuid = uuid.UUID(article_id)

    async def _run() -> bool:
        """Returns True if article is unique (should be enriched)."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(IntelArticle).where(IntelArticle.id == art_uuid)
            )
            article = result.scalar_one_or_none()
            if not article:
                logger.error("deduplicate_article: article %s not found", article_id)
                return False

            semantic_hash = compute_content_hash(article.title, article.content_raw)
            article.content_hash_semantic = semantic_hash

            # Check exact semantic hash
            dup_found, existing_id = await is_duplicate(semantic_hash, db)

            if not dup_found:
                # Check near-duplicates by title similarity
                near_dup_ids = await find_near_duplicates(article.title, db)
                # Exclude self
                near_dup_ids = [i for i in near_dup_ids if i != article_id]
                if near_dup_ids:
                    dup_found = True
                    existing_id = near_dup_ids[0]

            if dup_found and existing_id:
                try:
                    dup_uuid = uuid.UUID(existing_id)
                except ValueError:
                    dup_uuid = None

                article.is_duplicate = True
                article.duplicate_of_id = dup_uuid
                article.processing_status = "indexed"
                await db.commit()
                logger.info(
                    "deduplicate_article: article %s is duplicate of %s",
                    article_id, existing_id,
                )
                return False
            else:
                await db.commit()
                return True

    try:
        is_unique = asyncio.run(_run())
    except Exception as exc:
        logger.error("deduplicate_article %s failed: %s", article_id, exc)
        return

    if is_unique:
        enrich_article_task.apply_async(args=[article_id], queue="intel_enrich")


# ---------------------------------------------------------------------------
# enrich_article_task — LLM enrichment + tags + knowledge graph
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.enrich_article",
    bind=True,
    max_retries=3,
    queue="intel_enrich",
)
def enrich_article_task(self, article_id: str):
    """
    1. Call enrichment.enrich_article().
    2. Save IntelEnrichment.
    3. Call save_article_tags().
    4. Call extract_relations() for knowledge graph.
    5. Set article status='enriched'.
    6. Dispatch match_article_task.
    """
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import IntelArticle, IntelEnrichment
    from app.modules.intel.enrichment import enrich_article, generate_embedding, save_article_tags
    from app.modules.intel.knowledge_graph import extract_relations
    from sqlalchemy import select

    art_uuid = uuid.UUID(article_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(IntelArticle).where(IntelArticle.id == art_uuid)
            )
            article = result.scalar_one_or_none()
            if not article:
                logger.error("enrich_article_task: article %s not found", article_id)
                return

            # 1. Enrich with LLM
            try:
                enrichment_result, model_version = await enrich_article(article)
            except Exception as exc:
                logger.error("enrich_article_task: enrichment failed for %s: %s", article_id, exc)
                article.processing_status = "failed"
                await db.commit()
                raise

            # 2. Embedding (best-effort)
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
                industries=enrichment_result.industries,
                companies=enrichment_result.companies,
                commodities=enrichment_result.commodities,
                topics=enrichment_result.topics,
                trade_agreements=enrichment_result.trade_agreements,
                ports=enrichment_result.ports,
                currencies=enrichment_result.currencies,
                severity=enrichment_result.severity,
                urgency=enrichment_result.urgency,
                supply_chain_impact=enrichment_result.supply_chain_impact,
                price_effect=enrichment_result.price_effect,
                affected_industries=enrichment_result.affected_industries,
                affected_countries=enrichment_result.affected_countries,
            )
            db.add(enrichment)
            await db.flush()

            # 4. Save article tags
            try:
                await save_article_tags(art_uuid, enrichment_result, db)
            except Exception as exc:
                logger.warning("save_article_tags failed for %s: %s", article_id, exc)

            # 5. Extract knowledge graph relations
            try:
                await extract_relations(enrichment_result, art_uuid, db)
            except Exception as exc:
                logger.warning("extract_relations failed for %s: %s", article_id, exc)

            # 6. Update article status
            article.processing_status = "enriched"

            await db.commit()

            logger.info(
                "enrich_article_task %s: enriched (impact=%s, event=%s)",
                article_id, enrichment_result.impact_score, enrichment_result.event_type,
            )

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("enrich_article_task %s failed: %s", article_id, exc)
        raise self.retry(exc=exc, countdown=60)

    match_article_task.apply_async(args=[article_id], queue="intel_enrich")


# ---------------------------------------------------------------------------
# match_article_task — match to orgs + score
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.match_article",
    bind=True,
    queue="intel_enrich",
)
def match_article_task(self, article_id: str):
    """
    1. Call matcher.match_article_to_shipments().
    2. Score relevance for each org (recommender.score_article_for_org).
    3. Create IntelMatch records.
    4. Set article status='indexed'.
    5. For high-impact matches (score >= 0.7): dispatch send_alert_task.
    """
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import IntelArticle, IntelEnrichment, IntelMatch
    from app.modules.intel.matcher import match_article_to_shipments
    from app.modules.intel.recommender import score_article_for_org
    from sqlalchemy import select

    art_uuid = uuid.UUID(article_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(IntelArticle).where(IntelArticle.id == art_uuid)
            )
            article = result.scalar_one_or_none()
            if not article:
                logger.error("match_article_task: article %s not found", article_id)
                return

            enrich_result = await db.execute(
                select(IntelEnrichment).where(IntelEnrichment.article_id == art_uuid)
            )
            enrichment = enrich_result.scalar_one_or_none()
            if not enrichment:
                logger.warning("match_article_task: no enrichment for article %s", article_id)
                article.processing_status = "indexed"
                await db.commit()
                return

            # 1. Match to shipments (existing logic)
            matches = await match_article_to_shipments(art_uuid, enrichment, db)

            # 2. Score each unique org
            org_ids_seen = {m.org_id for m in matches}
            org_scores: dict[uuid.UUID, float] = {}
            for org_id in org_ids_seen:
                try:
                    score = await score_article_for_org(art_uuid, org_id, db)
                    org_scores[org_id] = score
                except Exception as exc:
                    logger.warning("score_article_for_org failed org=%s: %s", org_id, exc)

            # Update match_score on existing matches
            for match in matches:
                if match.org_id in org_scores:
                    match.match_score = org_scores[match.org_id]

            # 3. Set article status
            article.processing_status = "indexed"
            await db.commit()

            logger.info(
                "match_article_task %s: %d matches across %d orgs",
                article_id, len(matches), len(org_ids_seen),
            )

            # 4. Alert for high-impact (score >= 0.7)
            for org_id, score in org_scores.items():
                if score >= 0.7:
                    match_reason = next(
                        (m.match_reason for m in matches if m.org_id == org_id),
                        "High relevance score",
                    )
                    send_alert_task.apply_async(
                        args=[str(org_id), article_id, match_reason],
                        queue="intel_notify",
                    )

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("match_article_task %s failed: %s", article_id, exc)


# ---------------------------------------------------------------------------
# send_alert_task
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.send_alert", queue="intel_notify")
def send_alert_task(org_id: str, article_id: str, match_reason: str):
    """Create AlertDelivery record.  Log email content (SMTP placeholder)."""
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.models import AlertDelivery, IntelArticle, NotificationPreference
    from sqlalchemy import select

    org_uuid = uuid.UUID(org_id)
    art_uuid = uuid.UUID(article_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            # Load article for subject
            result = await db.execute(
                select(IntelArticle).where(IntelArticle.id == art_uuid)
            )
            article = result.scalar_one_or_none()
            if not article:
                return

            # Check notification preferences for active users in org
            prefs_result = await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.org_id == org_uuid,
                    NotificationPreference.is_active == True,
                )
            )
            prefs = list(prefs_result.scalars())

            channels: list[str] = ["in_app"]
            if prefs:
                # Union of all requested channels
                for pref in prefs:
                    channels = list(set(channels) | set(pref.delivery_channels or []))

            subject = f"Trade Alert: {article.title[:200]}"
            body_summary = (
                f"Reason: {match_reason}\n"
                f"Source: {article.url or 'N/A'}\n"
                f"Published: {article.published_at or 'unknown'}"
            )

            for channel in channels:
                delivery = AlertDelivery(
                    org_id=org_uuid,
                    article_id=art_uuid,
                    delivery_type=channel,
                    subject=subject,
                    body_summary=body_summary,
                    status="sent",
                )
                db.add(delivery)

                if channel == "email":
                    # SMTP placeholder
                    logger.info(
                        "[EMAIL PLACEHOLDER] To: org=%s | Subject: %s | Body: %s",
                        org_id, subject, body_summary,
                    )

            await db.commit()
            logger.info("send_alert_task: alerts created for org=%s article=%s", org_id, article_id)

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("send_alert_task failed org=%s article=%s: %s", org_id, article_id, exc)


# ---------------------------------------------------------------------------
# update_trending_topics_task — daily
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.update_trending_topics", queue="intel_enrich")
def update_trending_topics_task():
    """Daily: aggregate ArticleTag counts → TrendingTopic rows."""
    from app.core.database import AsyncSessionLocal
    from app.modules.intel.knowledge_graph import update_trending_topics

    async def _run():
        async with AsyncSessionLocal() as db:
            await update_trending_topics(db)

    try:
        asyncio.run(_run())
        logger.info("update_trending_topics_task: completed")
    except Exception as exc:
        logger.error("update_trending_topics_task failed: %s", exc)


# ---------------------------------------------------------------------------
# Legacy task aliases (keep backward compatibility)
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.poll_intel_source",
    bind=True,
    max_retries=3,
    queue="intel_collect",
)
def poll_intel_source(self, source_id: str):
    """Legacy alias for poll_source — kept for backward compatibility."""
    return poll_source.apply_async(args=[source_id], queue="intel_collect")


@celery_app.task(
    name="tasks.enrich_and_match_article",
    bind=True,
    max_retries=3,
    queue="intel_enrich",
)
def enrich_and_match_article(self, article_id: str):
    """Legacy alias — dispatches the new pipeline from enrich step."""
    enrich_article_task.apply_async(args=[article_id], queue="intel_enrich")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_hash(title: str, content: str) -> str:
    """SHA-256 of title + content (exact dedup hash)."""
    payload = f"{title}\n{content}"
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()
