"""
Base source adapter contract + built-in source seeding.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data transfer object returned by every adapter
# ---------------------------------------------------------------------------

@dataclass
class RawArticle:
    url: str
    title: str
    content_raw: str
    published_at: datetime | None
    source_name: str


# ---------------------------------------------------------------------------
# Abstract base adapter
# ---------------------------------------------------------------------------

class BaseSourceAdapter(ABC):
    @abstractmethod
    async def fetch(self) -> list[RawArticle]:
        """Fetch new articles from this source.  Must be idempotent."""


# ---------------------------------------------------------------------------
# Built-in source definitions
# ---------------------------------------------------------------------------

BUILTIN_SOURCES: list[dict] = [
    {
        "name": "EC Trade News",
        "source_type": "rss",
        "url": "https://ec.europa.eu/trade/rss.xml",
        "poll_cadence_minutes": 60,
    },
    {
        "name": "WTO News",
        "source_type": "rss",
        "url": "https://www.wto.org/english/res_e/resnew_e.xml",
        "poll_cadence_minutes": 120,
    },
    {
        "name": "HMRC Updates",
        "source_type": "rss",
        "url": "https://www.gov.uk/government/organisations/hm-revenue-customs.atom",
        "poll_cadence_minutes": 60,
    },
    {
        "name": "DBT Trade",
        "source_type": "rss",
        "url": "https://www.gov.uk/government/organisations/department-for-business-and-trade.atom",
        "poll_cadence_minutes": 120,
    },
    {
        "name": "UK Sanctions",
        "source_type": "sanctions_list",
        # Configurable — replace with the current OFSI consolidated list URL
        "url": "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.json",
        "poll_cadence_minutes": 360,
    },
]


# ---------------------------------------------------------------------------
# Idempotent seed function — called from main.py lifespan
# ---------------------------------------------------------------------------

async def seed_builtin_sources(db) -> None:
    """Insert BUILTIN_SOURCES that don't already exist (matched by name)."""
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
                source_type=spec["source_type"],
                url=spec["url"],
                poll_cadence_minutes=spec["poll_cadence_minutes"],
                is_active=True,
            )
            db.add(source)
            logger.info("Seeded built-in intel source: %s", spec["name"])

    await db.commit()
    logger.info("Built-in intel sources seeding complete.")
