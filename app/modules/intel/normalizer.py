"""
Trade Intelligence — normalizer.

Converts a ParsedArticle into a standard article dict ready for DB persistence.
Pure Python — no network, no LLM.
"""
from __future__ import annotations

from datetime import datetime

from app.modules.intel.parsers.base import ParsedArticle

# Source-name → known country mapping (ISO 3166-1 alpha-2)
_SOURCE_COUNTRY_MAP: dict[str, str] = {
    "HMRC Updates": "GB",
    "DBT Trade": "GB",
    "UK Sanctions (OFSI)": "GB",
    "UK Sanctions": "GB",
    "USITC News": "US",
    "US CBP Trade": "US",
    "EU Sanctions": "EU",
    "EC Trade News": "EU",
}


def normalize(parsed: ParsedArticle, source_name: str) -> dict:
    """
    Returns standard article dict:
    {
      "title": str (stripped, max 500 chars),
      "body": str (cleaned),
      "summary": str (max 300 chars),
      "source": str,
      "url": str,
      "published_at": datetime | None,
      "author": str | None,
      "country": str | None,    # inferred from source if known
      "language": str | None,
      "word_count": int,
      "image_url": str | None,
    }
    """
    title = (parsed.title or "").strip()[:500]
    body = (parsed.body or "").strip()
    summary = (parsed.summary or "").strip()[:300]
    url = (parsed.url or "").strip()
    author = (parsed.author or "").strip() or None
    language = (parsed.language or "").strip() or None
    image_url = (parsed.image_url or "").strip() or None

    # Infer country from source name
    country = _SOURCE_COUNTRY_MAP.get(source_name)

    # Ensure word_count is a non-negative int
    word_count = max(0, int(parsed.word_count or 0))

    return {
        "title": title,
        "body": body,
        "summary": summary,
        "source": source_name,
        "url": url,
        "published_at": parsed.published_at if isinstance(parsed.published_at, datetime) else None,
        "author": author,
        "country": country,
        "language": language,
        "word_count": word_count,
        "image_url": image_url,
    }
