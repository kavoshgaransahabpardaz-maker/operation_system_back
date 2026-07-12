"""
Trade Intelligence — pure-Python matching service.

RULES:
  - ZERO LLM calls.
  - ZERO network calls.
  - Only DB queries + Python set operations.
  - Matching logic: org interest profile × enrichment metadata.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intel.models import IntelEnrichment, IntelMatch, UserInterest
from app.modules.field_extraction.models import ExtractedField

logger = logging.getLogger(__name__)

_FUZZY_THRESHOLD = 80.0


def _hs_interests_hit(interests: list[UserInterest], enrichment: IntelEnrichment) -> list[str]:
    """
    Return human-readable hit reasons for HS-related interests.

    Logic:
      - hs_chapter "72"   → matches if "72"   is in enrichment.hs_chapters
      - hs_heading "7208" → matches if "7208"  is in enrichment.hs_headings
      - hs_code "720811"  → matches if enrichment has a chapter that is a prefix of
                            "720811" (i.e. "72" ⊆ "720811") OR a heading that is
                            a prefix of "720811" (i.e. "7208" ⊆ "720811")

    Returns list of reason strings (empty = no hit).
    """
    chapters = set(enrichment.hs_chapters or [])
    headings = set(enrichment.hs_headings or [])
    reasons: list[str] = []

    for i in interests:
        v = i.value
        if i.interest_type == "hs_chapter":
            if v in chapters:
                reasons.append(f"HS chapter {v}")
        elif i.interest_type == "hs_heading":
            if v in headings:
                reasons.append(f"HS heading {v}")
        elif i.interest_type == "hs_code":
            # The enrichment provides coarse codes; the org interest is a finer code.
            # A match means the article covers the same HS branch.
            if any(v.startswith(ch) for ch in chapters):
                reasons.append(f"HS code {v} (chapter match)")
            elif any(v.startswith(hd) for hd in headings):
                reasons.append(f"HS code {v} (heading match)")

    return reasons


def _industry_hit(interests: list[UserInterest], enrichment: IntelEnrichment) -> list[str]:
    article_industries = {ind.lower() for ind in (enrichment.industries or [])}
    reasons: list[str] = []
    for i in interests:
        if i.interest_type == "industry" and i.value.lower() in article_industries:
            reasons.append(f"industry {i.value}")
    return reasons


def _party_hit(interests: list[UserInterest], enrichment: IntelEnrichment) -> list[str]:
    article_companies = [c for c in (enrichment.companies or []) if c]
    reasons: list[str] = []
    if not article_companies:
        return reasons

    party_interests = [i.value for i in interests if i.interest_type == "party_name"]
    if not party_interests:
        return reasons

    try:
        from rapidfuzz import fuzz
        for party in party_interests:
            for company in article_companies:
                if fuzz.ratio(party.lower(), company.lower()) >= _FUZZY_THRESHOLD:
                    reasons.append(f"party {party}")
                    break
    except ImportError:
        party_set = {p.lower() for p in party_interests}
        for company in article_companies:
            if company.lower() in party_set:
                reasons.append(f"party {company}")
    return reasons


def _country_hit(interests: list[UserInterest], enrichment: IntelEnrichment) -> list[str]:
    countries = {c.upper() for c in (enrichment.countries or [])}
    reasons: list[str] = []
    for i in interests:
        if i.interest_type == "country" and i.value.upper() in countries:
            reasons.append(f"country {i.value}")
    return reasons


async def match_article_to_org(
    article_id: uuid.UUID,
    enrichment: IntelEnrichment,
    org_id: uuid.UUID,
    interests: list[UserInterest],
    db: AsyncSession,
) -> list[IntelMatch]:
    """
    Match one article against one org's interests.
    Returns the created IntelMatch records (not yet committed).
    """
    hit_reasons: list[str] = []
    hit_reasons += _hs_interests_hit(interests, enrichment)
    hit_reasons += _country_hit(interests, enrichment)
    hit_reasons += _industry_hit(interests, enrichment)
    hit_reasons += _party_hit(interests, enrichment)

    if not hit_reasons:
        return []

    match_reason = "; ".join(hit_reasons)

    # Collect matched HS prefixes for shipment lookup
    matched_hs_prefixes: set[str] = set()
    for i in interests:
        if i.interest_type == "hs_chapter":
            if i.value in set(enrichment.hs_chapters or []):
                matched_hs_prefixes.add(i.value)
        elif i.interest_type == "hs_heading":
            if i.value in set(enrichment.hs_headings or []):
                matched_hs_prefixes.add(i.value)
        elif i.interest_type == "hs_code":
            if any(i.value.startswith(ch) for ch in (enrichment.hs_chapters or [])):
                matched_hs_prefixes.add(i.value[:2])
            elif any(i.value.startswith(hd) for hd in (enrichment.hs_headings or [])):
                matched_hs_prefixes.add(i.value[:4])

    shipment_ids: list[uuid.UUID | None] = []

    if matched_hs_prefixes:
        hs_fields_result = await db.execute(
            select(ExtractedField).where(
                ExtractedField.org_id == org_id,
                ExtractedField.field_name == "hs_code",
            )
        )
        seen: set[uuid.UUID] = set()
        for field in hs_fields_result.scalars():
            raw = (field.value_raw or "").replace(".", "").strip()
            if any(raw.startswith(prefix) for prefix in matched_hs_prefixes):
                if field.shipment_id and field.shipment_id not in seen:
                    shipment_ids.append(field.shipment_id)
                    seen.add(field.shipment_id)

    if not shipment_ids:
        shipment_ids = [None]

    hs_match_count = len(matched_hs_prefixes)
    total_hs = len(set(enrichment.hs_chapters or []) | set(enrichment.hs_headings or []))

    created: list[IntelMatch] = []
    for shipment_id in shipment_ids:
        reason = match_reason
        if shipment_id:
            reason = f"{match_reason} ∩ your product records"
        match = IntelMatch(
            article_id=article_id,
            shipment_id=shipment_id,
            org_id=org_id,
            match_reason=reason,
            match_score=_compute_score(hs_match_count, total_hs, bool(shipment_id)),
        )
        db.add(match)
        created.append(match)

    return created


async def match_article_to_shipments(
    article_id: uuid.UUID,
    enrichment: IntelEnrichment,
    db: AsyncSession,
) -> list[IntelMatch]:
    """
    Match a newly enriched article against all org interest profiles.
    Checks all interest types: hs_chapter, hs_heading, hs_code, country, industry, party_name.
    """
    # Early exit: article has no matchable metadata
    has_hs = bool(enrichment.hs_chapters or enrichment.hs_headings)
    has_geo = bool(enrichment.countries)
    has_industry = bool(enrichment.industries)
    has_companies = bool(enrichment.companies)
    if not (has_hs or has_geo or has_industry or has_companies):
        logger.debug("Article %s has no matchable metadata — skipping", article_id)
        return []

    org_result = await db.execute(select(UserInterest.org_id).distinct())
    org_ids: list[uuid.UUID] = list(org_result.scalars())

    created_matches: list[IntelMatch] = []

    for org_id in org_ids:
        interest_result = await db.execute(
            select(UserInterest).where(UserInterest.org_id == org_id)
        )
        interests = list(interest_result.scalars())
        if not interests:
            continue

        org_matches = await match_article_to_org(article_id, enrichment, org_id, interests, db)
        created_matches.extend(org_matches)

    if created_matches:
        await db.commit()
        logger.info("Article %s matched to %d org/shipment pairs", article_id, len(created_matches))

    return created_matches


async def rematch_recent_articles_for_org(org_id: uuid.UUID, db: AsyncSession, days: int = 60) -> int:
    """
    Re-run matching for all enriched articles from the past `days` days against one org.
    Called when an org adds a new interest so existing articles can be matched retroactively.
    Skips articles that already have a match for this org.
    Returns count of new matches created.
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Load org interests
    interest_result = await db.execute(
        select(UserInterest).where(UserInterest.org_id == org_id)
    )
    interests = list(interest_result.scalars())
    if not interests:
        return 0

    # IDs already matched for this org
    existing_result = await db.execute(
        select(IntelMatch.article_id).where(IntelMatch.org_id == org_id)
    )
    already_matched: set[uuid.UUID] = set(existing_result.scalars())

    # Enriched articles from last `days` days not yet matched for this org
    from app.modules.intel.models import IntelArticle
    articles_result = await db.execute(
        select(IntelArticle.id, IntelEnrichment)
        .join(IntelEnrichment, IntelEnrichment.article_id == IntelArticle.id)
        .where(
            IntelArticle.ingested_at >= cutoff,
            IntelArticle.is_duplicate == False,
            IntelArticle.id.notin_(already_matched),
        )
    )
    rows = articles_result.all()

    total_new = 0
    for article_id, enrichment in rows:
        matches = await match_article_to_org(article_id, enrichment, org_id, interests, db)
        total_new += len(matches)

    if total_new:
        await db.commit()
        logger.info("rematch_recent_articles_for_org org=%s: %d new matches", org_id, total_new)

    return total_new


async def seed_org_interests(org_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Auto-seed UserInterest rows from shipment history (is_explicit=False).
    """
    hs_result = await db.execute(
        select(ExtractedField.value_raw).where(
            ExtractedField.org_id == org_id,
            ExtractedField.field_name == "hs_code",
        ).distinct()
    )
    hs_values: list[str] = [v for v in hs_result.scalars() if v]

    origin_result = await db.execute(
        select(ExtractedField.value_raw).where(
            ExtractedField.org_id == org_id,
            ExtractedField.field_name == "stated_origin",
        ).distinct()
    )
    origin_values: list[str] = [v for v in origin_result.scalars() if v]

    inserted = 0

    for hs_val in hs_values:
        hs_stripped = hs_val.replace(".", "").strip()
        for interest_type, value in [
            ("hs_chapter", hs_stripped[:2]),
            ("hs_heading", hs_stripped[:4]),
        ]:
            if not value or len(value) < 2:
                continue
            existing = await db.execute(
                select(UserInterest).where(
                    UserInterest.org_id == org_id,
                    UserInterest.interest_type == interest_type,
                    UserInterest.value == value,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(UserInterest(
                    org_id=org_id,
                    interest_type=interest_type,
                    value=value,
                    is_explicit=False,
                ))
                inserted += 1

    for country_val in origin_values:
        country = country_val.strip().upper()
        if not country:
            continue
        existing = await db.execute(
            select(UserInterest).where(
                UserInterest.org_id == org_id,
                UserInterest.interest_type == "country",
                UserInterest.value == country,
            )
        )
        if not existing.scalar_one_or_none():
            db.add(UserInterest(
                org_id=org_id,
                interest_type="country",
                value=country,
                is_explicit=False,
            ))
            inserted += 1

    if inserted:
        await db.commit()

    logger.info("Seeded %d interest rows for org %s", inserted, org_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_score(
    matched_hs_count: int,
    total_enrichment_hs: int,
    has_shipment: bool,
) -> float:
    base = 0.5 if matched_hs_count > 0 else 0.3  # non-HS matches still get base 0.3
    if total_enrichment_hs > 0:
        specificity = min(matched_hs_count / total_enrichment_hs, 1.0) * 0.3
    else:
        specificity = 0.0
    shipment_bonus = 0.2 if has_shipment else 0.0
    return round(min(base + specificity + shipment_bonus, 1.0), 4)
