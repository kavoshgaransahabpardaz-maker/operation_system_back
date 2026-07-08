"""
Trade Intelligence Module — ORM models.

Tables:
  intel_sources        — registered data sources (RSS, scraper, sanctions_list)
  intel_articles       — raw ingested articles (deduplicated by content_hash)
  intel_enrichments    — LLM-processed metadata (one per article)
  intel_matches        — join table: article × shipment (the product)
  user_interests       — org interest profile (auto-seeded + explicit)
  alert_deliveries     — delivery log
  article_tags         — structured tags extracted from enrichment
  companies            — extracted company entities
  article_companies    — article × company join
  knowledge_relations  — graph edges (subject → predicate → object)
  trending_topics      — materialized daily topic counts
  intel_jobs           — pipeline job tracking
  notification_preferences — per-user alert delivery settings
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IntelSource(Base):
    __tablename__ = "intel_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # rss / scraper / api / sanctions_list
    url: Mapped[str] = mapped_column(Text, nullable=False)
    poll_cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Extended fields
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)  # rss/api/html/xml/json/pdf/email/ftp
    parser_class: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. "BBCParser"
    credentials: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # encrypted API keys etc
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # per-source config
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    articles_collected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)  # 1=highest, 10=lowest


class IntelArticle(Base):
    __tablename__ = "intel_articles"
    __table_args__ = (
        Index("ix_intel_articles_content_hash", "content_hash"),
        Index("ix_intel_articles_source_id", "source_id"),
        Index("ix_intel_articles_published_at", "published_at"),
        Index("ix_intel_articles_processing_status", "processing_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_sources.id"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_raw: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Extended fields
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash_semantic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=True
    )
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="raw"
    )  # raw/parsed/normalized/enriched/indexed/failed


class IntelEnrichment(Base):
    __tablename__ = "intel_enrichments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=False, unique=True, index=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # tariff_change/sanctions/regulation/trade_agreement/market_notice/other
    countries: Mapped[list | None] = mapped_column(JSONB, nullable=True)        # list of ISO codes
    hs_chapters: Mapped[list | None] = mapped_column(JSONB, nullable=True)      # list of HS chapter strings
    hs_headings: Mapped[list | None] = mapped_column(JSONB, nullable=True)      # list of HS heading strings
    regulation_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # list of ref strings
    impact_score: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 1-5
    impact_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    # Stored as JSONB array (list[float]) — ready for pgvector migration later
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    enriched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Extended fields
    industries: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    companies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    commodities: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    topics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    trade_agreements: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ports: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    currencies: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    supply_chain_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_effect: Mapped[str | None] = mapped_column(String(20), nullable=True)
    affected_industries: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    affected_countries: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class IntelMatch(Base):
    __tablename__ = "intel_matches"
    __table_args__ = (
        Index("ix_intel_matches_article_id", "article_id"),
        Index("ix_intel_matches_shipment_id", "shipment_id"),
        Index("ix_intel_matches_org_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    match_reason: Mapped[str] = mapped_column(Text, nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0-1.0
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class UserInterest(Base):
    __tablename__ = "user_interests"
    __table_args__ = (
        UniqueConstraint("org_id", "interest_type", "value", name="uq_user_interests_org_type_value"),
        Index("ix_user_interests_org_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    interest_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # hs_chapter / hs_heading / country / party_name
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    is_explicit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (
        Index("ix_alert_deliveries_org_id", "org_id"),
        Index("ix_alert_deliveries_article_id", "article_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=True
    )
    delivery_type: Mapped[str] = mapped_column(String(20), nullable=False)  # email / in_app
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="sent")  # sent / failed


# ---------------------------------------------------------------------------
# New tables
# ---------------------------------------------------------------------------

class ArticleTag(Base):
    __tablename__ = "article_tags"
    __table_args__ = (
        Index("ix_article_tags_article_id", "article_id"),
        Index("ix_article_tags_tag_type", "tag_type"),
        Index("ix_article_tags_tag", "tag"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(255), nullable=False)
    tag_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # country/industry/company/product/commodity/hs_code/topic/currency/port/regulation/sanction/trade_agreement
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_companies_normalized_name"),
        Index("ix_companies_normalized_name", "normalized_name"),
        Index("ix_companies_country", "country"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ArticleCompany(Base):
    __tablename__ = "article_companies"
    __table_args__ = (
        Index("ix_article_companies_article_id", "article_id"),
        Index("ix_article_companies_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="mentioned"
    )  # mentioned/affected/sanctioned/party
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = (
        Index("ix_knowledge_relations_subject", "subject_type", "subject_value"),
        Index("ix_knowledge_relations_object", "object_type", "object_value"),
        Index("ix_knowledge_relations_article_id", "article_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # country/company/commodity/hs_code/regulation
    subject_value: Mapped[str] = mapped_column(String(500), nullable=False)
    predicate: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # exports/imports/sanctions/affects/regulates/trade_agreement_with
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_value: Mapped[str] = mapped_column(String(500), nullable=False)
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class TrendingTopic(Base):
    __tablename__ = "trending_topics"
    __table_args__ = (
        Index("ix_trending_topics_period", "period_start", "period_end"),
        Index("ix_trending_topics_type", "topic_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    topic_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # country/industry/commodity/hs_code/company
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class IntelJob(Base):
    __tablename__ = "intel_jobs"
    __table_args__ = (
        Index("ix_intel_jobs_source_id", "source_id"),
        Index("ix_intel_jobs_status", "status"),
        Index("ix_intel_jobs_job_type", "job_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_sources.id"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # collect/parse/enrich/deduplicate/translate/classify/match
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending/running/completed/failed
    articles_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_notification_prefs_org_user"),
        Index("ix_notification_preferences_org_id", "org_id"),
        Index("ix_notification_preferences_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    min_impact_score: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    event_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # empty = all types
    delivery_channels: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=lambda: ["in_app"]
    )  # in_app/email
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ArticleFeedback(Base):
    """Per-user thumbs-up / thumbs-down on an article, with optional comment."""

    __tablename__ = "article_feedback"
    __table_args__ = (
        UniqueConstraint("article_id", "user_id", name="uq_article_feedback_article_user"),
        Index("ix_article_feedback_article_id", "article_id"),
        Index("ix_article_feedback_org_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_articles.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    feedback: Mapped[str] = mapped_column(String(10), nullable=False)  # "like" | "dislike"
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
