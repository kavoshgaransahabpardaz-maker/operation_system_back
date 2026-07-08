"""
Base source adapter contract + built-in source seeding.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseSourceAdapter(ABC):
    @abstractmethod
    async def fetch(self): ...


# ---------------------------------------------------------------------------
# Built-in source definitions
# priority: 1=highest, 10=lowest
# category must match factory.py routing keys
# ---------------------------------------------------------------------------

BUILTIN_SOURCES: list[dict] = [
    # ── Existing core sources ────────────────────────────────────────────────
    {
        "name": "EC Trade News",
        "source_type": "rss",
        "category": "trade_news",
        "url": "https://ec.europa.eu/trade/rss.xml",
        "poll_cadence_minutes": 60,
        "priority": 1,
    },
    {
        "name": "WTO News",
        "source_type": "rss",
        "category": "regulation",
        "url": "https://www.wto.org/english/res_e/resnew_e.xml",
        "poll_cadence_minutes": 120,
        "priority": 1,
    },
    {
        "name": "HMRC Updates",
        "source_type": "rss",
        "category": "regulation",
        "url": "https://www.gov.uk/government/organisations/hm-revenue-customs.atom",
        "poll_cadence_minutes": 60,
        "priority": 1,
    },
    {
        "name": "DBT Trade",
        "source_type": "rss",
        "category": "trade_news",
        "url": "https://www.gov.uk/government/organisations/department-for-business-and-trade.atom",
        "poll_cadence_minutes": 120,
        "priority": 2,
    },
    {
        "name": "UK Sanctions",
        "source_type": "sanctions_list",
        "category": "sanctions_list",
        "url": "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.json",
        "poll_cadence_minutes": 360,
        "priority": 1,
    },
    # ── User-requested sources ───────────────────────────────────────────────
    {
        "name": "WCO News",
        "source_type": "rss",
        "category": "regulation",
        "url": "https://www.wcoomd.org/en/media/newsroom/2025/january.rss",
        "poll_cadence_minutes": 120,
        "priority": 1,
    },
    {
        "name": "BBC Business",
        "source_type": "rss",
        "category": "market_notice",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "poll_cadence_minutes": 60,
        "priority": 2,
    },
    {
        "name": "The Guardian Economics",
        "source_type": "rss",
        "category": "market_notice",
        "url": "https://www.theguardian.com/business/economics/rss",
        "poll_cadence_minutes": 60,
        "priority": 2,
    },
    {
        "name": "ICC News",
        "source_type": "rss",
        "category": "trade_news",
        "url": "https://iccwbo.org/news-publications/news/feed/",
        "poll_cadence_minutes": 120,
        "priority": 2,
    },
    {
        "name": "Global Trade Alert",
        "source_type": "rss",
        "category": "tariff",
        "url": "https://www.globaltradealert.org/rss",
        "poll_cadence_minutes": 120,
        "priority": 1,
    },
    {
        "name": "Trade Finance Global",
        "source_type": "rss",
        "category": "trade_news",
        "url": "https://tradefinanceglobal.com/feed/",
        "poll_cadence_minutes": 120,
        "priority": 3,
    },
    {
        "name": "UK Digital Trade Blog",
        "source_type": "rss",
        "category": "regulation",
        "url": "https://digitaltrade.blog.gov.uk/feed/",
        "poll_cadence_minutes": 240,
        "priority": 3,
    },
    {
        "name": "US Federal Register",
        "source_type": "rss",
        "category": "regulation",
        "url": "https://www.federalregister.gov/documents/current.rss",
        "poll_cadence_minutes": 240,
        "priority": 2,
    },
    {
        "name": "The Economist Finance",
        "source_type": "rss",
        "category": "market_notice",
        "url": "https://www.economist.com/finance-and-economics/rss.xml",
        "poll_cadence_minutes": 240,
        "priority": 3,
    },
    {
        "name": "Sandler Travis Trade Report",
        "source_type": "rss",
        "category": "trade_news",
        "url": "https://www.strtrade.com/feed/",
        "poll_cadence_minutes": 240,
        "priority": 3,
    },
]


# ---------------------------------------------------------------------------
# Idempotent seed function — called from main.py lifespan
# ---------------------------------------------------------------------------

async def seed_builtin_sources(db) -> None:
    """Insert BUILTIN_SOURCES that don't already exist (matched by name).
    Also back-fills `category` on existing rows that were seeded without it."""
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
                priority=spec.get("priority", 5),
                is_active=True,
            )
            db.add(source)
            logger.info("Seeded built-in intel source: %s", spec["name"])
        else:
            # Back-fill category + priority if missing
            if not existing.category and spec.get("category"):
                existing.category = spec["category"]
            if existing.priority == 5 and spec.get("priority") != 5:
                existing.priority = spec["priority"]

    await db.commit()
    logger.info("Built-in intel sources seeding complete.")
