"""
Pydantic schemas for the intel module API.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# IntelSource
# ---------------------------------------------------------------------------

class IntelSourceOut(BaseModel):
    id: uuid.UUID
    name: str
    source_type: str | None
    category: str | None
    url: str
    poll_cadence_minutes: int
    is_active: bool
    last_polled_at: datetime | None
    last_error: str | None
    health_status: str
    articles_collected: int
    priority: int
    created_at: datetime

    model_config = {"from_attributes": True}


class IntelSourceCreate(BaseModel):
    name: str
    source_type: str | None = None
    category: str | None = None
    url: str
    poll_cadence_minutes: int = 60
    is_active: bool = True
    priority: int = 5
    config: dict | None = None


class IntelSourceUpdate(BaseModel):
    name: str | None = None
    source_type: str | None = None
    category: str | None = None
    url: str | None = None
    poll_cadence_minutes: int | None = None
    is_active: bool | None = None
    priority: int | None = None
    config: dict | None = None
    health_status: str | None = None


# ---------------------------------------------------------------------------
# IntelArticle
# ---------------------------------------------------------------------------

class IntelArticleOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    url: str | None
    title: str
    content_raw: str
    published_at: datetime | None
    ingested_at: datetime
    language: str | None = None
    author: str | None = None
    image_url: str | None = None
    word_count: int | None = None
    is_duplicate: bool = False
    processing_status: str = "raw"

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# IntelEnrichment
# ---------------------------------------------------------------------------

class IntelEnrichmentOut(BaseModel):
    id: uuid.UUID
    article_id: uuid.UUID
    summary: str | None
    event_type: str | None
    countries: list[str] | None
    hs_chapters: list[str] | None
    hs_headings: list[str] | None
    regulation_refs: list[str] | None
    impact_score: int | None
    impact_rationale: str | None
    model_version: str
    enriched_at: datetime
    # Extended fields
    industries: list[str] | None = None
    companies: list[str] | None = None
    commodities: list[str] | None = None
    topics: list[str] | None = None
    trade_agreements: list[str] | None = None
    ports: list[str] | None = None
    currencies: list[str] | None = None
    severity: str | None = None
    urgency: str | None = None
    supply_chain_impact: str | None = None
    price_effect: str | None = None
    affected_industries: list[str] | None = None
    affected_countries: list[str] | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# IntelMatch
# ---------------------------------------------------------------------------

class IntelMatchOut(BaseModel):
    id: uuid.UUID
    article_id: uuid.UUID
    shipment_id: uuid.UUID | None
    org_id: uuid.UUID
    match_reason: str
    match_score: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Feed response (article + enrichment + matches)
# ---------------------------------------------------------------------------

class IntelFeedItem(BaseModel):
    article: IntelArticleOut
    enrichment: IntelEnrichmentOut | None
    matches: list[IntelMatchOut]
    match_reason: str | None  # primary reason from first match


# ---------------------------------------------------------------------------
# UserInterest
# ---------------------------------------------------------------------------

class UserInterestOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    interest_type: str
    value: str
    is_explicit: bool
    created_at: datetime

    model_config = {"from_attributes": True}


VALID_INTEREST_TYPES = {
    "country", "hs_chapter", "hs_heading", "hs_code", "party_name", "industry",
}


class UserInterestCreate(BaseModel):
    interest_type: str
    value: str

    @classmethod
    def validate_interest(cls, interest_type: str, value: str) -> str:
        """Returns cleaned value or raises ValueError."""
        import re
        v = value.strip()
        if not v:
            raise ValueError("value cannot be empty")
        t = interest_type.strip().lower()
        if t not in VALID_INTEREST_TYPES:
            raise ValueError(f"interest_type must be one of: {sorted(VALID_INTEREST_TYPES)}")
        if t == "country":
            if not re.fullmatch(r"[A-Z]{2}", v.upper()):
                raise ValueError("country must be a 2-letter ISO alpha-2 code (e.g. GB, US, DE)")
            return v.upper()
        if t == "hs_chapter":
            if not re.fullmatch(r"\d{2}", v):
                raise ValueError("hs_chapter must be a 2-digit number (e.g. 72)")
            return v
        if t == "hs_heading":
            if not re.fullmatch(r"\d{4}", v):
                raise ValueError("hs_heading must be a 4-digit number (e.g. 7208)")
            return v
        if t == "hs_code":
            if not re.fullmatch(r"\d{6,10}", v):
                raise ValueError("hs_code must be 6–10 digits")
            return v
        if t in ("party_name", "industry"):
            if not re.search(r"[A-Za-z]", v):
                raise ValueError(f"{t.replace('_', ' ')} must contain letters")
            if re.search(r"\d", v):
                raise ValueError(f"{t.replace('_', ' ')} must not contain numbers")
            return v
        return v


# ---------------------------------------------------------------------------
# AlertDelivery
# ---------------------------------------------------------------------------

class AlertDeliveryOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    article_id: uuid.UUID | None
    delivery_type: str
    subject: str | None
    body_summary: str | None
    delivered_at: datetime
    status: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# ArticleTag
# ---------------------------------------------------------------------------

class ArticleTagOut(BaseModel):
    id: uuid.UUID
    article_id: uuid.UUID
    tag: str
    tag_type: str
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# IntelJob
# ---------------------------------------------------------------------------

class IntelJobOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID | None
    job_type: str
    status: str
    articles_processed: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# TrendingTopic
# ---------------------------------------------------------------------------

class TrendingTopicOut(BaseModel):
    id: uuid.UUID
    topic: str
    topic_type: str
    article_count: int
    period_start: date
    period_end: date
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# KnowledgeRelation
# ---------------------------------------------------------------------------

class KnowledgeRelationOut(BaseModel):
    id: str
    subject_type: str
    subject_value: str
    predicate: str
    object_type: str
    object_value: str
    article_id: str | None
    confidence: float
    created_at: str


# ---------------------------------------------------------------------------
# NotificationPreference
# ---------------------------------------------------------------------------

class NotificationPreferenceOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID
    min_impact_score: int
    event_types: list[str]
    delivery_channels: list[str]
    is_active: bool
    digest_hour: int
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationPreferenceUpdate(BaseModel):
    min_impact_score: int | None = None
    event_types: list[str] | None = None
    delivery_channels: list[str] | None = None
    is_active: bool | None = None
    digest_hour: int | None = None


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class TrendingResponse(BaseModel):
    topics: list[TrendingTopicOut]


class HeatmapEntry(BaseModel):
    country: str
    article_count: int


class EventTypeCount(BaseModel):
    event_type: str
    article_count: int


class ImpactTimelineEntry(BaseModel):
    date: str
    avg_impact_score: float
    article_count: int


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    article_id: str
    title: str
    url: str | None
    published_at: str | None
    ingested_at: str | None
    processing_status: str
    rank: float
    match_source: str


# ---------------------------------------------------------------------------
# Article Feedback
# ---------------------------------------------------------------------------

class ArticleFeedbackCreate(BaseModel):
    feedback: str  # "like" | "dislike"
    comment: str | None = None


class ArticleFeedbackOut(BaseModel):
    id: uuid.UUID
    article_id: uuid.UUID
    user_id: uuid.UUID
    feedback: str
    comment: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MyFeedbackOut(BaseModel):
    """Current user's feedback on a single article (null if none given)."""
    feedback: str | None  # "like" | "dislike" | null
    comment: str | None


# ---------------------------------------------------------------------------
# Filter options (for frontend dropdowns)
# ---------------------------------------------------------------------------

class ImpactLevel(BaseModel):
    level: int
    label: str
    description: str


class EventTypeOption(BaseModel):
    value: str
    label: str
    description: str


class FilterOptionsOut(BaseModel):
    countries: list[str]       # ISO alpha-2 codes found in article_tags
    industries: list[str]      # industry tags found in article_tags
    event_types: list[EventTypeOption]
    impact_scale: list[ImpactLevel]


# ---------------------------------------------------------------------------
# Personalized summary
# ---------------------------------------------------------------------------

class PersonalizedSummaryOut(BaseModel):
    article_id: uuid.UUID
    summary: str              # AI-generated summary tailored to org interests
    relevant_interests: list[str]  # which interests matched
    general_summary: str | None    # original enrichment summary for comparison


# ---------------------------------------------------------------------------
# Interest type catalogue
# ---------------------------------------------------------------------------

class InterestTypeOption(BaseModel):
    type: str
    label: str
    description: str
    example: str
    format_hint: str


# ---------------------------------------------------------------------------
# Source preferences per org
# ---------------------------------------------------------------------------

class OrgSourcePreferenceOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    is_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgSourcePreferencePatch(BaseModel):
    is_enabled: bool
