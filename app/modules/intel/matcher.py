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


async def match_article_to_shipments(
    article_id: uuid.UUID,
    enrichment: IntelEnrichment,
    db: AsyncSession,
) -> list[IntelMatch]:
    """
    Match a newly enriched article against all org interest profiles.

    Algorithm (pure Python + DB queries — no LLM):
      1. Load all distinct org_ids from UserInterest.
      2. For each org: load its UserInterest rows.
      3. For each interest row check against enrichment:
           - hs_chapter  → interest.value in enrichment.hs_chapters
           - hs_heading  → interest.value in enrichment.hs_headings
           - country     → interest.value in enrichment.countries
           - party_name  → not used here (handled in sanctions path)
      4. If hit: find shipments in that org with matching HS codes.
      5. Create IntelMatch records with machine-readable match_reason.
      6. Commit and return created matches.
    """
    enrichment_chapters: set[str] = set(enrichment.hs_chapters or [])
    enrichment_headings: set[str] = set(enrichment.hs_headings or [])
    enrichment_countries: set[str] = set(enrichment.countries or [])

    # Early exit: nothing to match against
    if not (enrichment_chapters or enrichment_headings or enrichment_countries):
        logger.debug(
            "Article %s has no chapters/headings/countries — skipping match", article_id
        )
        return []

    # 1. Distinct org_ids that have interests
    org_result = await db.execute(
        select(UserInterest.org_id).distinct()
    )
    org_ids: list[uuid.UUID] = list(org_result.scalars())

    created_matches: list[IntelMatch] = []

    for org_id in org_ids:
        # 2. Load interest rows for this org
        interest_result = await db.execute(
            select(UserInterest).where(UserInterest.org_id == org_id)
        )
        interests: list[UserInterest] = list(interest_result.scalars())

        hit_reasons: list[str] = []
        matched_chapters: set[str] = set()
        matched_headings: set[str] = set()

        for interest in interests:
            itype = interest.interest_type
            val = interest.value

            if itype == "hs_chapter" and val in enrichment_chapters:
                hit_reasons.append(f"HS chapter {val}")
                matched_chapters.add(val)
            elif itype == "hs_heading" and val in enrichment_headings:
                hit_reasons.append(f"HS heading {val}")
                matched_headings.add(val)
            elif itype == "country" and val in enrichment_countries:
                hit_reasons.append(f"country {val}")

        if not hit_reasons:
            continue

        # Build machine-readable reason string
        match_reason = "; ".join(hit_reasons)

        # 3. Find shipments in this org with matching HS codes via extracted_fields
        #    Only do shipment lookup if we have HS hits (skip for country-only matches)
        shipment_ids_to_match: list[uuid.UUID | None] = []

        if matched_chapters or matched_headings:
            # Build HS prefixes to filter extracted fields
            hs_prefixes = list(matched_chapters) + list(matched_headings)

            # Query extracted fields for hs_code in this org
            hs_fields_result = await db.execute(
                select(ExtractedField).where(
                    ExtractedField.org_id == org_id,
                    ExtractedField.field_name == "hs_code",
                )
            )
            hs_fields: list[ExtractedField] = list(hs_fields_result.scalars())

            shipment_ids_seen: set[uuid.UUID] = set()
            for field in hs_fields:
                raw_val = field.value_raw or ""
                # Match if field value starts with any of our HS prefixes
                if any(raw_val.startswith(prefix) for prefix in hs_prefixes):
                    if field.shipment_id and field.shipment_id not in shipment_ids_seen:
                        shipment_ids_to_match.append(field.shipment_id)
                        shipment_ids_seen.add(field.shipment_id)

            if not shipment_ids_to_match:
                # No shipments found — still create an org-level match with no shipment
                shipment_ids_to_match = [None]
        else:
            # Country-only match — org-level, no specific shipment
            shipment_ids_to_match = [None]

        # 4. Create IntelMatch records
        for shipment_id in shipment_ids_to_match:
            reason = match_reason
            if shipment_id:
                reason = f"HS {'; '.join(matched_chapters | matched_headings)} ∩ your product records"

            match = IntelMatch(
                article_id=article_id,
                shipment_id=shipment_id,
                org_id=org_id,
                match_reason=reason,
                match_score=_compute_score(
                    len(matched_chapters) + len(matched_headings),
                    len(enrichment_chapters) + len(enrichment_headings),
                    bool(shipment_id),
                ),
            )
            db.add(match)
            created_matches.append(match)

    if created_matches:
        await db.commit()
        logger.info(
            "Article %s matched to %d org/shipment pairs", article_id, len(created_matches)
        )

    return created_matches


async def seed_org_interests(org_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Auto-seed UserInterest rows from shipment history (is_explicit=False).

    Reads extracted_fields for hs_code and stated_origin, then inserts
    UserInterest rows.  Skips duplicates (UPSERT-style via ignore).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # 1. Gather unique hs_code values for this org
    hs_result = await db.execute(
        select(ExtractedField.value_raw).where(
            ExtractedField.org_id == org_id,
            ExtractedField.field_name == "hs_code",
        ).distinct()
    )
    hs_values: list[str] = [v for v in hs_result.scalars() if v]

    # 2. Gather unique stated_origin (country) values
    origin_result = await db.execute(
        select(ExtractedField.value_raw).where(
            ExtractedField.org_id == org_id,
            ExtractedField.field_name == "stated_origin",
        ).distinct()
    )
    origin_values: list[str] = [v for v in origin_result.scalars() if v]

    inserted = 0

    # 3. Upsert hs_code interests (derive chapter = first 2 chars, heading = first 4 chars)
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

    # 4. Upsert country interests
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
    matched_count: int,
    total_enrichment_count: int,
    has_shipment: bool,
) -> float:
    """Simple heuristic score 0.0-1.0."""
    base = 0.5 if matched_count > 0 else 0.0
    if total_enrichment_count > 0:
        specificity = min(matched_count / total_enrichment_count, 1.0) * 0.3
    else:
        specificity = 0.0
    shipment_bonus = 0.2 if has_shipment else 0.0
    return round(min(base + specificity + shipment_bonus, 1.0), 4)
