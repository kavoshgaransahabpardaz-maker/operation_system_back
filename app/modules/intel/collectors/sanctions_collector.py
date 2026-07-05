"""
Sanctions list collector.

Downloads UK OFSI ConList.json and EU sanctions XML.
Each sanctioned entity becomes a RawArticle.
title = "Sanctions: {entity_name}"
Detects format from URL (json vs xml).
On any error: logs and returns [].
"""
from __future__ import annotations

import json
import logging

import httpx

from app.modules.intel.collectors.base import BaseCollector, RawArticle

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 60  # sanctions lists can be large


class SanctionsCollector(BaseCollector):
    async def collect(self) -> list[RawArticle]:
        url = self.source.get("url", "")
        source_name = self.source.get("name", "")

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                raw_content = response.text
        except Exception as exc:
            logger.error("SanctionsCollector HTTP error for %s: %s", url, exc)
            return []

        # Detect format from URL or content-type
        is_xml = url.endswith(".xml") or "<" in raw_content[:100]

        if is_xml:
            return self._parse_xml(raw_content, url, source_name)
        else:
            return self._parse_json(raw_content, url, source_name)

    def _parse_json(self, raw_content: str, url: str, source_name: str) -> list[RawArticle]:
        """Parse UK OFSI JSON format."""
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            logger.error("SanctionsCollector: could not parse JSON from %s: %s", url, exc)
            return []

        persons: list[dict] = data.get("DesignatedPersons", [])
        if not persons:
            persons = data.get("designatedPersons", data.get("Entries", []))

        articles: list[RawArticle] = []
        for person in persons:
            try:
                entity_name = _extract_entity_name_json(person)
                if not entity_name:
                    continue

                title = f"Sanctions: {entity_name}"
                content = json.dumps(person, ensure_ascii=False, default=str)

                articles.append(
                    RawArticle(
                        url=url,
                        title=title,
                        content_raw=content,
                        published_at=None,
                        source_name=source_name,
                    )
                )
            except Exception as exc:
                logger.warning("SanctionsCollector: error parsing JSON entity: %s", exc)
                continue

        logger.info("SanctionsCollector parsed %d JSON entities from %s", len(articles), url)
        return articles

    def _parse_xml(self, raw_content: str, url: str, source_name: str) -> list[RawArticle]:
        """Parse EU sanctions XML format."""
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(raw_content)
        except Exception as exc:
            logger.error("SanctionsCollector: could not parse XML from %s: %s", url, exc)
            return []

        articles: list[RawArticle] = []

        # EU sanctions XML uses SubjectEntity elements
        # Try common tag names
        entity_tags = ["SubjectEntity", "sanctionEntity", "entity", "person", "Entry"]
        ns_prefix = ""

        # Detect namespace
        if root.tag.startswith("{"):
            ns_prefix = root.tag.split("}")[0] + "}"

        entities: list = []
        for tag in entity_tags:
            full_tag = f"{ns_prefix}{tag}"
            found = root.findall(f".//{full_tag}")
            if found:
                entities = found
                break

        if not entities:
            # Fallback: treat every child as an entity
            entities = list(root)

        for entity in entities:
            try:
                entity_name = _extract_entity_name_xml(entity, ns_prefix)
                if not entity_name:
                    continue

                title = f"Sanctions: {entity_name}"
                # Serialize XML element as text content
                try:
                    import xml.etree.ElementTree as ET
                    content = ET.tostring(entity, encoding="unicode")
                except Exception:
                    content = entity_name

                articles.append(
                    RawArticle(
                        url=url,
                        title=title,
                        content_raw=content,
                        published_at=None,
                        source_name=source_name,
                    )
                )
            except Exception as exc:
                logger.warning("SanctionsCollector: error parsing XML entity: %s", exc)
                continue

        logger.info("SanctionsCollector parsed %d XML entities from %s", len(articles), url)
        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_entity_name_json(person: dict) -> str:
    """Best-effort extraction of entity name from OFSI JSON."""
    names_list = person.get("Names", person.get("names", []))
    if names_list:
        first = names_list[0] if isinstance(names_list, list) else names_list
        if isinstance(first, dict):
            parts = [
                first.get("Name6", ""),
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

    for key in ("EntityName", "FullName", "fullName", "Name"):
        val = person.get(key)
        if val:
            return str(val)

    return ""


def _extract_entity_name_xml(entity, ns_prefix: str) -> str:
    """Best-effort extraction of entity name from EU sanctions XML element."""
    # Try common name element patterns
    name_tags = [
        f"{ns_prefix}nameAlias",
        f"{ns_prefix}wholeName",
        f"{ns_prefix}name",
        f"{ns_prefix}Name",
        f"{ns_prefix}firstName",
    ]

    for tag in name_tags:
        elem = entity.find(f".//{tag}")
        if elem is not None:
            # Check 'wholeName' attribute or text
            whole = elem.get("wholeName") or elem.get("WholeName") or elem.text
            if whole and whole.strip():
                return whole.strip()

    # Fallback: check entity attributes
    for attr in ("wholeName", "name", "Name"):
        val = entity.get(attr)
        if val:
            return str(val).strip()

    return ""
