"""
Trade Intelligence — LLM enrichment service.

Calls OpenAI to extract structured metadata from raw articles and optionally
generates a text embedding for semantic search.

Rules:
  - HS codes: ONLY extract when explicitly mentioned — return [] if uncertain.
  - model_version is stored on every enrichment record — never lose it.
  - response_format=json_object gates the output through EnrichmentResult Pydantic model.
"""
from __future__ import annotations

import json
import logging
import uuid

from pydantic import BaseModel, field_validator

from app.core.config import settings

logger = logging.getLogger(__name__)

_ENRICHMENT_MODEL = "gpt-4o-mini-2024-07-18"
_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMS = 1536

_SYSTEM_PROMPT = """You are a trade compliance analyst extracting structured metadata from trade news articles.
Respond ONLY with a valid JSON object with exactly these keys:

- summary: ≤80 words plain English summary focused on trade impact
- event_type: MUST be one of these — choose the MOST specific match:
    * tariff_change — any new/changed import or export duties, anti-dumping measures, countervailing duties, quota changes
    * sanctions — sanctions lists, asset freezes, export controls, embargoes, denied parties
    * regulation — customs procedures, compliance requirements, border controls, licensing, product standards, labour law affecting trade
    * trade_agreement — FTAs, bilateral/multilateral deals, MoUs, negotiations, trade disputes (WTO panels)
    * market_notice — freight rates, shipping schedules, port congestion, carrier announcements, capacity changes, commodity/energy price movements
    * company_news — corporate earnings, M&A, strategic partnerships, supply agreements, restructuring, IPOs, layoffs for companies in trade-relevant sectors (shipping, manufacturing, logistics, commodities, retail, tech hardware)
    * economic_data — macroeconomic indicators, GDP, PMI, trade statistics, sector growth/contraction, government fiscal policy, interest rates, currency policy with trade implications
    * supply_chain — supply chain disruptions or shifts, logistics partnerships, distribution network changes, nearshoring/reshoring, infrastructure investments affecting trade flows
    * geopolitical — political developments, elections, conflicts, military actions, territorial disputes that affect trade routes, market access, or trade relations
    * other — ONLY use if the article has no meaningful connection to trade, supply chains, or international commerce (e.g. pure entertainment, sports, personal finance unrelated to trade)
- countries: ISO 3166-1 alpha-2 codes (uppercase). Include ALL countries mentioned OR clearly implied (trade routes, ports, company headquarters, product origins). E.g. if the article mentions "Asia-Europe route" include key countries. If "US tariffs on China" include ["US","CN"].
- hs_chapters: 2-digit HS chapter strings ONLY if explicitly stated (e.g. "72" for steel). Empty list if not mentioned.
- hs_headings: 4-digit HS heading strings ONLY if explicitly stated. Empty list if not mentioned.
- regulation_refs: regulation/law reference strings explicitly mentioned (e.g. "EU 2024/123", "Section 232")
- impact_score: integer 1-5:
    1 = general background/informational
    2 = worth monitoring, minor operational impact
    3 = moderate impact on costs or compliance procedures
    4 = significant — affects pricing, routing, or compliance for active traders
    5 = immediate action required (new sanction, emergency tariff, port closure)
- impact_rationale: 1-2 sentences explaining why this score
- industries: affected industry sectors (e.g. ["shipping", "steel", "automotive", "agriculture", "energy"])
- companies: company names mentioned
- commodities: specific goods/commodities (e.g. ["LNG", "steel coil", "soybeans", "crude oil"])
- topics: trade topics (e.g. ["anti-dumping", "freight rates", "port congestion", "export controls"])
- trade_agreements: trade agreement or deal names mentioned
- ports: port names mentioned
- currencies: ISO 4217 currency codes explicitly mentioned
- severity: low / medium / high / critical (based on breadth of traders affected)
- urgency: informational / monitor / act_soon / immediate
- supply_chain_impact: brief description of supply chain effect or null
- price_effect: increase / decrease / neutral / unknown (effect on trade costs/prices)
- affected_industries: industries that will feel the impact
- affected_countries: ISO alpha-2 codes of countries whose traders are directly impacted
"""


class EnrichmentResult(BaseModel):
    summary: str
    event_type: str
    countries: list[str]
    hs_chapters: list[str]
    hs_headings: list[str]
    regulation_refs: list[str]
    impact_score: int
    impact_rationale: str
    # Extended fields
    industries: list[str] = []
    companies: list[str] = []
    commodities: list[str] = []
    topics: list[str] = []
    trade_agreements: list[str] = []
    ports: list[str] = []
    currencies: list[str] = []
    severity: str = "low"
    urgency: str = "informational"
    supply_chain_impact: str | None = None
    price_effect: str | None = "unknown"
    affected_industries: list[str] = []
    affected_countries: list[str] = []

    @field_validator(
        "countries", "hs_chapters", "hs_headings", "regulation_refs",
        "industries", "companies", "commodities", "topics",
        "trade_agreements", "ports", "currencies",
        "affected_industries", "affected_countries",
        mode="before",
    )
    @classmethod
    def coerce_to_list(cls, v):
        """LLM sometimes returns a string instead of a list — wrap it."""
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v or []

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        allowed = {
            "tariff_change", "sanctions", "regulation",
            "trade_agreement", "market_notice",
            "company_news", "economic_data", "supply_chain", "geopolitical",
            "other",
        }
        return v if v in allowed else "other"

    @field_validator("impact_score")
    @classmethod
    def validate_impact_score(cls, v: int) -> int:
        return max(1, min(5, v))

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        return v if v in allowed else "low"

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v: str) -> str:
        allowed = {"informational", "monitor", "act_soon", "immediate"}
        return v if v in allowed else "informational"

    @field_validator("price_effect")
    @classmethod
    def validate_price_effect(cls, v: str | None) -> str | None:
        allowed = {"positive", "negative", "neutral", "unknown", None}
        return v if v in allowed else "unknown"


async def enrich_article(article) -> tuple[EnrichmentResult, str]:
    """
    Enrich an IntelArticle using OpenAI.

    Returns (EnrichmentResult, model_version_string).
    model_version is extracted from the API response — always stored.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # Truncate to keep within token budget (title + first 6000 chars of content)
    text_snippet = f"Title: {article.title}\n\n{article.content_raw[:6000]}"

    response = await client.chat.completions.create(
        model=_ENRICHMENT_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Article:\n{text_snippet}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    model_version: str = response.model  # e.g. "gpt-4o-mini-2024-07-18"
    raw = json.loads(response.choices[0].message.content)

    result = EnrichmentResult(**raw)
    return result, model_version


async def generate_embedding(text: str) -> list[float]:
    """
    Generate a 1536-dim text embedding using OpenAI text-embedding-3-small.

    Stored in IntelEnrichment.embedding as JSON array (JSONB column).
    Ready to migrate to pgvector when available.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.embeddings.create(
        model=_EMBEDDING_MODEL,
        input=text[:8000],  # stay within 8k token limit
        dimensions=_EMBEDDING_DIMS,
    )
    return response.data[0].embedding


async def save_article_tags(
    article_id: uuid.UUID,
    enrichment: EnrichmentResult,
    db,
) -> None:
    """
    Create ArticleTag rows for all enrichment fields that carry tag data.

    Tags created:
    - countries         → tag_type='country'
    - industries        → tag_type='industry'
    - companies         → tag_type='company'
    - commodities       → tag_type='commodity'
    - hs_chapters       → tag_type='hs_code'
    - hs_headings       → tag_type='hs_code'
    - topics            → tag_type='topic'
    - trade_agreements  → tag_type='trade_agreement'
    - ports             → tag_type='port'
    - currencies        → tag_type='currency'
    """
    from app.modules.intel.models import ArticleTag

    tag_groups: list[tuple[str, list[str]]] = [
        ("country", enrichment.countries),
        ("industry", enrichment.industries),
        ("company", enrichment.companies),
        ("commodity", enrichment.commodities),
        ("hs_code", enrichment.hs_chapters),
        ("hs_code", enrichment.hs_headings),
        ("topic", enrichment.topics),
        ("trade_agreement", enrichment.trade_agreements),
        ("port", enrichment.ports),
        ("currency", enrichment.currencies),
    ]

    for tag_type, values in tag_groups:
        for value in (values or []):
            if not value or not value.strip():
                continue
            tag = ArticleTag(
                article_id=article_id,
                tag=value.strip(),
                tag_type=tag_type,
            )
            db.add(tag)

    # Don't commit here — caller manages the transaction
