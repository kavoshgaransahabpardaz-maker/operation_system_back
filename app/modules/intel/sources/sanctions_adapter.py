"""
Sanctions list adapter.

Downloads the UK/EU consolidated sanctions list and converts each entry into
a RawArticle so it flows through the same dedup + enrichment pipeline.

Currently supports:
  - UK OFSI consolidated list (JSON format)
    URL: https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.json
    (configurable via IntelSource.url — mark in .env as SANCTIONS_LIST_URL if needed)
"""
from __future__ import annotations

import json
import logging

import httpx

from app.modules.intel.sources.base import BaseSourceAdapter, RawArticle

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 60  # sanctions lists can be large


class SanctionsAdapter(BaseSourceAdapter):
    def __init__(self, source_name: str, list_url: str) -> None:
        self.source_name = source_name
        self.list_url = list_url

    async def fetch(self) -> list[RawArticle]:
        """Download and parse the sanctions list.  Returns list[RawArticle]."""
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(self.list_url)
                response.raise_for_status()
                raw_content = response.text
        except httpx.HTTPError as exc:
            logger.error("SanctionsAdapter HTTP error for %s: %s", self.list_url, exc)
            raise

        articles: list[RawArticle] = []

        # ------------------------------------------------------------------
        # UK OFSI JSON format
        # Structure: {"DesignatedPersons": [{"Names": [...], ...}, ...]}
        # ------------------------------------------------------------------
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError:
            logger.error("SanctionsAdapter: could not parse JSON from %s", self.list_url)
            return articles

        persons: list[dict] = data.get("DesignatedPersons", [])
        if not persons:
            # Try alternative key names
            persons = data.get("designatedPersons", data.get("Entries", []))

        for person in persons:
            entity_name = _extract_entity_name(person)
            if not entity_name:
                continue

            title = f"Sanctions: {entity_name}"
            # Serialise the full entry as JSON content so enrichment/fuzzy
            # matching has all structured data available.
            content = json.dumps(person, ensure_ascii=False, default=str)

            articles.append(
                RawArticle(
                    url=self.list_url,
                    title=title,
                    content_raw=content,
                    published_at=None,  # sanctions lists don't carry per-entry dates
                    source_name=self.source_name,
                )
            )

        logger.info(
            "SanctionsAdapter parsed %d entries from %s", len(articles), self.list_url
        )
        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_entity_name(person: dict) -> str:
    """Best-effort extraction of a human-readable entity name from OFSI JSON."""
    # Try Names array first (OFSI 2022 format)
    names_list = person.get("Names", person.get("names", []))
    if names_list:
        first = names_list[0] if isinstance(names_list, list) else names_list
        if isinstance(first, dict):
            parts = [
                first.get("Name6", ""),  # primary name field in OFSI
                first.get("Name1", ""),
                first.get("Name2", ""),
                first.get("Name3", ""),
                first.get("Name4", ""),
                first.get("Name5", ""),
            ]
            name = " ".join(p for p in parts if p).strip()
            if name:
                return name
        elif isinstance(first, str):
            return first

    # Fallback: EntityName or FullName
    for key in ("EntityName", "FullName", "fullName", "Name"):
        val = person.get(key)
        if val:
            return str(val)

    return ""
