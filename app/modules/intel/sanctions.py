"""
Trade Intelligence — Sanctions screening service.

Fuzzy-matches shipment party names (shipper, consignee) against all
sanctions list entries ingested via the sanctions_list source adapter.

Uses the existing names_match() from mismatch.fuzzy (same threshold as org
settings) so behaviour is consistent across the platform.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityAction, ActivityLog
from app.modules.field_extraction.models import ExtractedField
from app.modules.flags.models import Flag, FlagSeverity, FlagStatus, FlagType
from app.modules.intel.models import IntelArticle, IntelSource
from app.modules.mismatch.fuzzy import names_match
from app.modules.org_settings.service import get_settings

logger = logging.getLogger(__name__)

# Fields that carry party names
_PARTY_FIELD_NAMES = ("party_shipper", "party_consignee")

# Default fuzzy threshold if org settings unavailable
_DEFAULT_THRESHOLD = 0.93


async def screen_shipment_parties(shipment_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Screen all party names in a shipment against the sanctions list.

    1. Load extracted fields with field_name in ('party_shipper', 'party_consignee').
    2. Load sanctions source IDs.
    3. Load all IntelArticle rows from sanctions sources (title contains entity name).
    4. Fuzzy-match each party name against each sanctions entity.
    5. On hit → create Flag(MISMATCH, CRITICAL) and log FLAG_CREATED.
    """
    # 1. Load party fields for this shipment
    party_result = await db.execute(
        select(ExtractedField).where(
            ExtractedField.shipment_id == shipment_id,
            ExtractedField.field_name.in_(_PARTY_FIELD_NAMES),
        )
    )
    party_fields: list[ExtractedField] = list(party_result.scalars())

    if not party_fields:
        logger.debug("No party fields for shipment %s — sanctions screen skipped", shipment_id)
        return

    # Determine org_id from first field
    org_id = party_fields[0].org_id

    # Fetch org settings for the name_match_threshold
    threshold = _DEFAULT_THRESHOLD
    if org_id:
        org_settings = await get_settings(org_id, db)
        if org_settings:
            threshold = org_settings.name_match_threshold

    # 2. Load sanctions source IDs
    sanctions_sources_result = await db.execute(
        select(IntelSource.id).where(IntelSource.source_type == "sanctions_list")
    )
    sanctions_source_ids = list(sanctions_sources_result.scalars())

    if not sanctions_source_ids:
        logger.debug("No sanctions sources registered — screen skipped")
        return

    # 3. Load all sanctions articles (title = "Sanctions: {entity_name}")
    sanctions_result = await db.execute(
        select(IntelArticle).where(
            IntelArticle.source_id.in_(sanctions_source_ids)
        )
    )
    sanctions_articles: list[IntelArticle] = list(sanctions_result.scalars())

    if not sanctions_articles:
        logger.debug("No sanctions articles ingested — screen skipped")
        return

    # Build entity name list once (strip "Sanctions: " prefix)
    entity_names: list[str] = []
    for art in sanctions_articles:
        name = art.title
        if name.startswith("Sanctions: "):
            name = name[len("Sanctions: "):]
        entity_names.append(name)

    # 4. Fuzzy-match each party field against each entity
    flags_created = 0
    for field in party_fields:
        party_name = field.value_raw or ""
        if not party_name.strip():
            continue

        for entity_name in entity_names:
            if names_match(party_name, entity_name, threshold):
                # 5. Create Flag
                flag_title = f"Potential sanctions match: {party_name}"

                # Deduplication: skip if identical open flag already exists
                existing_result = await db.execute(
                    select(Flag).where(
                        Flag.shipment_id == shipment_id,
                        Flag.flag_type == FlagType.MISMATCH,
                        Flag.title == flag_title,
                        Flag.status == FlagStatus.OPEN,
                    )
                )
                if existing_result.scalar_one_or_none():
                    continue

                flag = Flag(
                    shipment_id=shipment_id,
                    org_id=org_id,
                    flag_type=FlagType.MISMATCH,
                    severity=FlagSeverity.CRITICAL,
                    title=flag_title,
                    description=(
                        f"Party name '{party_name}' matches sanctions list entry "
                        f"'{entity_name}'. Manual review required."
                    ),
                    conflicting_values=[
                        {
                            "document_id": str(field.document_id),
                            "field_name": field.field_name,
                            "value_raw": field.value_raw,
                            "page_number": field.page_number,
                            "sanctions_entity": entity_name,
                        }
                    ],
                    status=FlagStatus.OPEN,
                )
                db.add(flag)
                flags_created += 1

                # Log FLAG_CREATED
                log_entry = ActivityLog(
                    org_id=org_id,
                    shipment_id=shipment_id,
                    action=ActivityAction.FLAG_CREATED,
                    details={
                        "flag_type": "mismatch",
                        "severity": "critical",
                        "party_name": party_name,
                        "matched_entity": entity_name,
                    },
                )
                db.add(log_entry)

                # Only flag the first matching entity per party to avoid flood
                break

    if flags_created:
        await db.commit()
        logger.warning(
            "Sanctions screen for shipment %s: %d critical flags created",
            shipment_id, flags_created,
        )
    else:
        logger.info(
            "Sanctions screen for shipment %s: no matches found", shipment_id
        )
