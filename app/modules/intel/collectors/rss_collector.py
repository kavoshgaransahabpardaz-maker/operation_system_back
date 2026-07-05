"""
RSS/Atom feed collector.

Uses feedparser + httpx.  Handles RSS 2.0 and Atom.
Returns list[RawArticle].  On any error: logs and returns [].
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import feedparser
import httpx

from app.modules.intel.collectors.base import BaseCollector, RawArticle

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # seconds


class RssCollector(BaseCollector):
    async def collect(self) -> list[RawArticle]:
        url = self.source.get("url", "")
        source_name = self.source.get("name", "")

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                raw_content = response.text
        except Exception as exc:
            logger.error("RssCollector HTTP error for %s: %s", url, exc)
            return []

        try:
            feed = feedparser.parse(raw_content)
        except Exception as exc:
            logger.error("RssCollector feedparser error for %s: %s", url, exc)
            return []

        articles: list[RawArticle] = []
        for entry in feed.entries:
            try:
                title = getattr(entry, "title", "") or ""
                article_url = getattr(entry, "link", "") or ""
                author = getattr(entry, "author", None)
                image_url = _extract_image(entry)

                # Prefer full content, fall back to summary
                if hasattr(entry, "content") and entry.content:
                    content = entry.content[0].get("value", "") or ""
                else:
                    content = getattr(entry, "summary", "") or ""

                # Strip HTML tags
                content = _strip_html(content)
                if not content:
                    content = title  # degenerate fallback

                published_at = _parse_date(entry)

                articles.append(
                    RawArticle(
                        url=article_url,
                        title=title.strip(),
                        content_raw=content.strip(),
                        published_at=published_at,
                        author=author,
                        image_url=image_url,
                        source_name=source_name,
                    )
                )
            except Exception as exc:
                logger.warning("RssCollector: error parsing entry from %s: %s", url, exc)
                continue

        logger.info("RssCollector fetched %d entries from %s", len(articles), url)
        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(entry) -> datetime | None:
    """Best-effort published date parsing from a feedparser entry."""
    from email.utils import parsedate_to_datetime

    for attr in ("published_parsed", "updated_parsed"):
        ts = getattr(entry, attr, None)
        if ts:
            try:
                return datetime(*ts[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except Exception:
                pass

    return None


def _strip_html(text: str) -> str:
    """Remove HTML tags using stdlib re — no external dependencies."""
    return re.sub(r"<[^>]+>", " ", text)


def _extract_image(entry) -> str | None:
    """Try to extract a thumbnail/image URL from a feedparser entry."""
    # media:thumbnail
    media_thumb = getattr(entry, "media_thumbnail", None)
    if media_thumb and isinstance(media_thumb, list) and media_thumb:
        url = media_thumb[0].get("url")
        if url:
            return url

    # enclosures
    enclosures = getattr(entry, "enclosures", None)
    if enclosures:
        for enc in enclosures:
            mime = enc.get("type", "")
            if mime.startswith("image/"):
                return enc.get("href") or enc.get("url")

    return None
