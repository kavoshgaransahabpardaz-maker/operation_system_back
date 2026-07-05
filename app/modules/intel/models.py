"""
Trade Intelligence Module — ORM models.

Tables:
  intel_sources      — registered data sources (RSS, scraper, sanctions_list)
  intel_articles     — raw ingested articles (deduplicated by content_hash)
  intel_enrichments  — LLM-processed metadata (one per article)
  intel_matches      — join table: article × shipment (the product)
  user_interests     — org interest profile (auto-seeded + explicit)
  alert_deliveries   — delivery log
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
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


class IntelArticle(Base):
    __tablename__ = "intel_articles"
    __table_args__ = (
        Index("ix_intel_articles_content_hash", "content_hash"),
        Index("ix_intel_articles_source_id", "source_id"),
        Index("ix_intel_articles_published_at", "published_at"),
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
