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

_SYSTEM_PROMPT = """You are a trade compliance analyst.
Analyze the article and respond ONLY with a JSON object with exactly these keys:
- summary: string, ≤80 words, plain English
- event_type: one of tariff_change, sanctions, regulation, trade_agreement, market_notice, other
- countries: list of ISO 3166-1 alpha-2 codes (uppercase) — only countries explicitly named
- hs_chapters: list of HS chapter strings (2-digit, e.g. "72") — ONLY if explicitly stated in the article, empty list if uncertain
- hs_headings: list of HS heading strings (4-digit, e.g. "7208") — ONLY if explicitly stated, empty list if uncertain
- regulation_refs: list of regulation reference strings (e.g. "EU 2024/123") — only when explicitly mentioned
- impact_score: integer 1-5 where 1=informational, 5=immediate action required for affected traders
- impact_rationale: string, 1-2 sentences explaining the impact score
- industries: list of industry strings (e.g. ["steel", "automotive", "agriculture"])
- companies: list of company names mentioned in the article
- commodities: list of commodity strings (e.g. ["steel", "wheat", "oil"])
- topics: list of trade topic strings (e.g. ["anti-dumping", "safeguard", "quota"])
- trade_agreements: list of trade agreement names (e.g. ["CPTPP", "UK-EU TCA"])
- ports: list of port names mentioned
- currencies: list of ISO 4217 currency codes mentioned (e.g. ["USD", "EUR"])
- severity: one of low, medium, high, critical
- urgency: one of informational, monitor, act_soon, immediate
- supply_chain_impact: string (brief description) or null if not applicable
- price_effect: one of positive, negative, neutral, unknown
- affected_industries: list of industries impacted by this event
- affected_countries: list of ISO 3166-1 alpha-2 codes of countries impacted
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

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        allowed = {
            "tariff_change", "sanctions", "regulation",
            "trade_agreement", "market_notice", "other",
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

    # Truncate to keep within token budget (title + first 3000 chars of content)
    text_snippet = f"Title: {article.title}\n\n{article.content_raw[:3000]}"

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
