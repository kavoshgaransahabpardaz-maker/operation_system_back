import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document_classification.models import ClassificationResult
from app.modules.document_storage.models import Document, DocumentStatus
from app.modules.email_integration.models import EmailAttachment, EmailRecord, MailboxConnection
from app.modules.field_extraction.models import ExtractedField, ExtractedFieldStatus
from app.modules.flags.models import Flag, FlagSeverity, FlagStatus
from app.modules.shipment_identification.models import Shipment, ShipmentReference
from app.modules.shipment_workspace.schemas import (
    AttentionShipment,
    DashboardStats,
    DocumentSummary,
    RecentEmailOut,
    ShipmentDetail,
    ShipmentReferenceOut,
)


async def get_shipment_detail(db: AsyncSession, org_id: uuid.UUID, shipment_id: uuid.UUID) -> ShipmentDetail:
    shipment_result = await db.execute(
        select(Shipment).where(Shipment.id == shipment_id, Shipment.org_id == org_id)
    )
    shipment = shipment_result.scalar_one_or_none()
    if not shipment:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")

    refs_result = await db.execute(
        select(ShipmentReference).where(ShipmentReference.shipment_id == shipment_id)
    )
    refs = [ShipmentReferenceOut(ref_type=r.ref_type, ref_value=r.ref_value) for r in refs_result.scalars()]

    docs_result = await db.execute(
        select(Document).where(Document.shipment_id == shipment_id).order_by(Document.created_at.desc())
    )
    docs_raw = list(docs_result.scalars())

    doc_ids = [d.id for d in docs_raw]
    classifications: dict[uuid.UUID, ClassificationResult] = {}
    if doc_ids:
        cls_result = await db.execute(
            select(ClassificationResult).where(ClassificationResult.document_id.in_(doc_ids))
        )
        for c in cls_result.scalars():
            classifications[c.document_id] = c

    documents = []
    for d in docs_raw:
        cls = classifications.get(d.id)
        documents.append(DocumentSummary(
            id=d.id,
            filename=d.filename,
            content_type=d.content_type,
            source=d.source,
            status=d.status,
            doc_type=cls.doc_type if cls else None,
            confidence=cls.confidence if cls else None,
            created_at=d.created_at,
        ))

    return ShipmentDetail(
        id=shipment.id,
        org_id=shipment.org_id,
        status=shipment.status,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        references=refs,
        documents=documents,
    )


async def get_dashboard_stats(db: AsyncSession, org_id: uuid.UUID) -> DashboardStats:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    total_shipments_result = await db.execute(
        select(func.count()).select_from(Shipment).where(Shipment.org_id == org_id)
    )
    total_shipments = total_shipments_result.scalar() or 0

    docs_today_result = await db.execute(
        select(func.count()).select_from(Document).where(
            Document.org_id == org_id, Document.created_at >= today_start
        )
    )
    documents_imported_today = docs_today_result.scalar() or 0

    unclassified_result = await db.execute(
        select(func.count()).select_from(Document).where(
            Document.org_id == org_id,
            Document.status.in_([DocumentStatus.UPLOADED, DocumentStatus.OCR_PENDING,
                                   DocumentStatus.OCR_PROCESSING, DocumentStatus.UNMATCHED]),
        )
    )
    unclassified_documents = unclassified_result.scalar() or 0

    review_result = await db.execute(
        select(func.count()).select_from(Document).where(
            Document.org_id == org_id,
            Document.status == DocumentStatus.NEEDS_REVIEW,
        )
    )
    # Group by shipment
    review_shipments_result = await db.execute(
        select(func.count(Document.shipment_id.distinct())).select_from(Document).where(
            Document.org_id == org_id,
            Document.status == DocumentStatus.NEEDS_REVIEW,
            Document.shipment_id.isnot(None),
        )
    )
    shipments_requiring_review = review_shipments_result.scalar() or 0

    recent_emails_result = await db.execute(
        select(EmailRecord, MailboxConnection).join(
            MailboxConnection, EmailRecord.connection_id == MailboxConnection.id
        ).where(
            EmailRecord.org_id == org_id
        ).order_by(EmailRecord.received_at.desc()).limit(10)
    )
    recent_emails = []
    for email_record, conn in recent_emails_result:
        att_count_result = await db.execute(
            select(func.count()).select_from(EmailAttachment).where(
                EmailAttachment.email_record_id == email_record.id
            )
        )
        att_count = att_count_result.scalar() or 0
        recent_emails.append(RecentEmailOut(
            id=email_record.id,
            subject=email_record.subject,
            sender=email_record.sender,
            provider=conn.provider,
            received_at=email_record.received_at,
            attachment_count=att_count,
        ))

    # --- Enhanced fields ---

    # Count open critical flags
    critical_flags_result = await db.execute(
        select(func.count()).select_from(Flag).where(
            Flag.org_id == org_id,
            Flag.status == FlagStatus.OPEN,
            Flag.severity == FlagSeverity.CRITICAL,
        )
    )
    open_flags_critical = critical_flags_result.scalar() or 0

    # Count open warning flags
    warning_flags_result = await db.execute(
        select(func.count()).select_from(Flag).where(
            Flag.org_id == org_id,
            Flag.status == FlagStatus.OPEN,
            Flag.severity == FlagSeverity.WARNING,
        )
    )
    open_flags_warning = warning_flags_result.scalar() or 0

    # Count extracted fields with status='extracted' and confidence < 0.70
    pending_reviews_result = await db.execute(
        select(func.count()).select_from(ExtractedField).where(
            ExtractedField.org_id == org_id,
            ExtractedField.status == ExtractedFieldStatus.EXTRACTED,
            ExtractedField.confidence < 0.70,
        )
    )
    pending_field_reviews = pending_reviews_result.scalar() or 0

    # Attention queue: up to 5 shipments with open critical flags
    # Get shipment_ids that have open critical flags
    critical_ship_result = await db.execute(
        select(Flag.shipment_id, func.count(Flag.id).label("flag_count"))
        .where(
            Flag.org_id == org_id,
            Flag.status == FlagStatus.OPEN,
            Flag.severity == FlagSeverity.CRITICAL,
        )
        .group_by(Flag.shipment_id)
        .order_by(func.count(Flag.id).desc())
        .limit(5)
    )
    attention_queue: list[AttentionShipment] = []
    for row in critical_ship_result:
        ship_id = row[0]
        flag_count = row[1]
        # short_id: first 8 chars of the UUID
        short_id = str(ship_id)[:8]
        attention_queue.append(AttentionShipment(
            id=ship_id,
            short_id=short_id,
            flag_count=flag_count,
        ))

    return DashboardStats(
        total_shipments=total_shipments,
        documents_imported_today=documents_imported_today,
        unclassified_documents=unclassified_documents,
        shipments_requiring_review=shipments_requiring_review,
        recent_email_imports=recent_emails,
        open_flags_critical=open_flags_critical,
        open_flags_warning=open_flags_warning,
        pending_field_reviews=pending_field_reviews,
        attention_queue=attention_queue,
    )
