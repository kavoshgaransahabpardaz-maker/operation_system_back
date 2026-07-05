"""
Generic parser — works for any RawArticle.

- Cleans HTML from content_raw using stdlib html.parser (no new deps)
- Extracts sentences, estimates word_count
- Generates summary: first 3 sentences (no LLM — deterministic)
- Detects language using langdetect (already in requirements)
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

from app.modules.intel.parsers.base import BaseParser, ParsedArticle

logger = logging.getLogger(__name__)


class GenericParser(BaseParser):
    def parse(self, raw_article) -> ParsedArticle:
        title = (getattr(raw_article, "title", "") or "").strip()
        raw_body = getattr(raw_article, "content_raw", "") or ""
        url = getattr(raw_article, "url", "") or ""
        source = getattr(raw_article, "source_name", "") or ""
        published_at = getattr(raw_article, "published_at", None)
        author = getattr(raw_article, "author", None)
        image_url = getattr(raw_article, "image_url", None)

        # Clean HTML
        body = _clean_html(raw_body)

        # Normalise whitespace
        body = re.sub(r"\s+", " ", body).strip()

        # Word count
        word_count = len(body.split()) if body else 0

        # Generate summary (first 3 sentences, deterministic)
        summary = _extract_summary(body, max_sentences=3, max_chars=300)

        # Detect language
        language = _detect_language(body or title)

        return ParsedArticle(
            title=title[:500],
            body=body,
            summary=summary,
            source=source,
            url=url,
            published_at=published_at,
            author=author,
            language=language,
            image_url=image_url,
            word_count=word_count,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _HTMLCleaner(HTMLParser):
    """stdlib HTMLParser that strips tags and decodes entities."""
    _SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _clean_html(text: str) -> str:
    """Remove HTML tags and decode entities using stdlib HTMLParser."""
    cleaner = _HTMLCleaner()
    try:
        cleaner.feed(text)
        return cleaner.get_text()
    except Exception:
        # Fallback: regex strip
        return re.sub(r"<[^>]+>", " ", text)


def _extract_summary(body: str, max_sentences: int = 3, max_chars: int = 300) -> str:
    """Extract first N sentences as summary, capped at max_chars."""
    if not body:
        return ""

    # Split on sentence-ending punctuation followed by space/newline
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    selected = sentences[:max_sentences]
    summary = " ".join(selected)

    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0] + "..."

    return summary


def _detect_language(text: str) -> str | None:
    """Detect language using langdetect.  Returns ISO 639-1 code or None."""
    if not text or len(text) < 20:
        return None
    try:
        from langdetect import detect, LangDetectException
        return detect(text[:500])
    except Exception:
        return None
