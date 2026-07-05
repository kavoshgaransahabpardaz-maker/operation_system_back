"""
Trade Intelligence — source registry.

All sources come from the DB.  This file only defines:
  1. BUILTIN_SOURCES — seed list inserted on startup (idempotent).
  2. COLLECTOR_MAP   — source category → collector class name.

Never hardcode a source anywhere else.
"""
from __future__ import annotations

BUILTIN_SOURCES: list[dict] = [
    # RSS sources
    {
        "name": "EC Trade News",
        "category": "rss",
        "source_type": "rss",
        "url": "https://ec.europa.eu/trade/rss.xml",
        "poll_cadence_minutes": 60,
        "priority": 2,
    },
    {
        "name": "WTO News",
        "category": "rss",
        "source_type": "rss",
        "url": "https://www.wto.org/english/res_e/resnew_e.xml",
        "poll_cadence_minutes": 120,
        "priority": 3,
    },
    {
        "name": "HMRC Updates",
        "category": "rss",
        "source_type": "rss",
        "url": "https://www.gov.uk/government/organisations/hm-revenue-customs.atom",
        "poll_cadence_minutes": 60,
        "priority": 2,
    },
    {
        "name": "DBT Trade",
        "category": "rss",
        "source_type": "rss",
        "url": "https://www.gov.uk/government/organisations/department-for-business-and-trade.atom",
        "poll_cadence_minutes": 120,
        "priority": 3,
    },
    {
        "name": "USITC News",
        "category": "rss",
        "source_type": "rss",
        "url": "https://www.usitc.gov/press_room/news_release/rss.xml",
        "poll_cadence_minutes": 120,
        "priority": 3,
    },
    {
        "name": "US CBP Trade",
        "category": "rss",
        "source_type": "rss",
        "url": "https://www.cbp.gov/trade/rss.xml",
        "poll_cadence_minutes": 60,
        "priority": 2,
    },
    {
        "name": "ICC Trade",
        "category": "rss",
        "source_type": "rss",
        "url": "https://iccwbo.org/feed/",
        "poll_cadence_minutes": 180,
        "priority": 4,
    },
    # Sanctions lists
    {
        "name": "UK Sanctions (OFSI)",
        "category": "sanctions_list",
        "source_type": "sanctions_list",
        "url": "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.json",
        "poll_cadence_minutes": 360,
        "priority": 1,
    },
    {
        "name": "EU Sanctions",
        "category": "sanctions_list",
        "source_type": "sanctions_list",
        "url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content",
        "poll_cadence_minutes": 360,
        "priority": 1,
    },
]

# Map source category → collector class name
COLLECTOR_MAP: dict[str, str] = {
    "rss": "RssCollector",
    "sanctions_list": "SanctionsCollector",
    "html": "HtmlCollector",
    "api": "ApiCollector",
    "pdf": "PdfCollector",
}


async def seed_builtin_sources(db) -> None:
    """Insert BUILTIN_SOURCES that don't already exist (matched by name). Idempotent."""
    from sqlalchemy import select
    from app.modules.intel.models import IntelSource

    for spec in BUILTIN_SOURCES:
        result = await db.execute(
            select(IntelSource).where(IntelSource.name == spec["name"])
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            source = IntelSource(
                name=spec["name"],
                source_type=spec.get("source_type"),
                category=spec.get("category"),
                url=spec["url"],
                poll_cadence_minutes=spec.get("poll_cadence_minutes", 60),
                is_active=True,
                priority=spec.get("priority", 5),
            )
            db.add(source)

    await db.commit()
