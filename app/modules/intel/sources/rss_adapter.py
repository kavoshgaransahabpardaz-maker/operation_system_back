"""
RSS/Atom feed adapter.

Parses standard RSS and Atom feeds using feedparser.
Handles: EC trade news, WTO news, HMRC updates, DBT trade.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.modules.intel.sources.base import BaseSourceAdapter, RawArticle

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # seconds


class RssAdapter(BaseSourceAdapter):
    def __init__(self, url: str, source_name: str) -> None:
        self.url = url
        self.source_name = source_name

    async def fetch(self) -> list[RawArticle]:
        """Fetch and parse an RSS/Atom feed.  Returns list[RawArticle]."""
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(self.url)
                response.raise_for_status()
                raw_content = response.text
        except httpx.HTTPError as exc:
            logger.error("RssAdapter HTTP error for %s: %s", self.url, exc)
            raise

        feed = feedparser.parse(raw_content)

        articles: list[RawArticle] = []
        for entry in feed.entries:
            title = getattr(entry, "title", "") or ""
            url = getattr(entry, "link", "") or ""

            # Prefer full content, fall back to summary
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "") or ""
            else:
                content = getattr(entry, "summary", "") or ""

            # Strip minimal HTML if present (no heavy dep — just strip tags crudely)
            content = _strip_html(content)
            if not content:
                content = title  # degenerate fallback

            published_at = _parse_date(entry)

            articles.append(
                RawArticle(
                    url=url,
                    title=title.strip(),
                    content_raw=content.strip(),
                    published_at=published_at,
                    source_name=self.source_name,
                )
            )

        logger.info("RssAdapter fetched %d entries from %s", len(articles), self.url)
        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(entry) -> datetime | None:
    """Best-effort published date parsing from a feedparser entry."""
    # feedparser gives a time_struct in entry.published_parsed or entry.updated_parsed
    for attr in ("published_parsed", "updated_parsed"):
        ts = getattr(entry, attr, None)
        if ts:
            try:
                return datetime(*ts[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    # Fallback: try raw string fields
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except Exception:
                pass

    return None


def _strip_html(text: str) -> str:
    """Naively remove HTML tags without a parser dependency."""
    import re
    return re.sub(r"<[^>]+>", " ", text)
