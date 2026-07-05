"""
Pydantic schemas for the intel module API.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# IntelSource
# ---------------------------------------------------------------------------

class IntelSourceOut(BaseModel):
    id: uuid.UUID
    name: str
    source_type: str | None
    url: str
    poll_cadence_minutes: int
    is_active: bool
    last_polled_at: datetime | None
    last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


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


class UserInterestCreate(BaseModel):
    interest_type: str  # hs_chapter / hs_heading / country / party_name
    value: str


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
