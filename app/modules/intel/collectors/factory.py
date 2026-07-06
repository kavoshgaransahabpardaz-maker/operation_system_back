"""
Collector factory — returns correct BaseCollector instance based on source.category.
"""
from __future__ import annotations

from app.modules.intel.collectors.base import BaseCollector


def get_collector(source: dict) -> BaseCollector:
    """
    Return the correct collector instance based on source['category'].

    source is an IntelSource serialised to dict (or a dict-like object).
    Raises ValueError for unknown categories.
    """
    # Accept both dict and ORM object
    if hasattr(source, "__dict__"):
        category = getattr(source, "category", None) or getattr(source, "source_type", None)
        source_dict = {
            "url": getattr(source, "url", ""),
            "name": getattr(source, "name", ""),
            "category": category,
            "source_type": getattr(source, "source_type", None),
            "config": getattr(source, "config", None),
            "credentials": getattr(source, "credentials", None),
        }
    else:
        category = source.get("category") or source.get("source_type")
        source_dict = source

    if category in ("rss", "trade_news", "tariff", "regulation"):
        from app.modules.intel.collectors.rss_collector import RssCollector
        return RssCollector(source_dict)

    elif category in ("sanctions_list",):
        from app.modules.intel.collectors.sanctions_collector import SanctionsCollector
        return SanctionsCollector(source_dict)

    elif category == "html":
        from app.modules.intel.collectors.html_collector import HtmlCollector
        return HtmlCollector(source_dict)

    elif category == "pdf":
        from app.modules.intel.collectors.pdf_collector import PdfCollector
        return PdfCollector(source_dict)

    elif category == "api":
        # API collector — fall back to RSS (handles JSON feeds too)
        from app.modules.intel.collectors.rss_collector import RssCollector
        return RssCollector(source_dict)

    else:
        raise ValueError(f"Unknown collector category: {category!r}")
