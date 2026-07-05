"""
Trade Intelligence — Alert delivery service.

For now: create AlertDelivery record and log to activity_log.
Email sending: placeholder (log the would-be email content, ready for SMTP hookup).
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityAction, ActivityLog
from app.modules.intel.models import AlertDelivery, IntelMatch

logger = logging.getLogger(__name__)


async def send_alert(
    org_id: uuid.UUID,
    article_id: uuid.UUID,
    matches: list[IntelMatch],
    db: AsyncSession,
) -> AlertDelivery:
    """
    Persist an AlertDelivery record and emit a log entry.

    Email sending is a placeholder — log the would-be email content.
    Ready for SMTP/SendGrid hookup via the body_summary field.
    """
    match_reasons = "; ".join(m.match_reason for m in matches if m.match_reason)
    subject = f"Trade Intelligence Alert — {len(matches)} match(es)"
    body_summary = (
        f"New trade intelligence article matched your organisation's interests.\n"
        f"Article ID: {article_id}\n"
        f"Match reasons: {match_reasons or 'N/A'}\n"
        f"Affected shipments: {', '.join(str(m.shipment_id) for m in matches if m.shipment_id) or 'none'}"
    )

    # Log placeholder email
    logger.info(
        "[ALERT PLACEHOLDER] Would send email to org %s:\nSubject: %s\n%s",
        org_id, subject, body_summary,
    )

    # Persist delivery record
    delivery = AlertDelivery(
        org_id=org_id,
        article_id=article_id,
        delivery_type="in_app",
        subject=subject,
        body_summary=body_summary,
        status="sent",
    )
    db.add(delivery)

    # Activity log
    log_entry = ActivityLog(
        org_id=org_id,
        action=ActivityAction.FLAG_CREATED,  # reuse closest existing action
        details={
            "event": "intel_alert_sent",
            "article_id": str(article_id),
            "match_count": len(matches),
        },
    )
    db.add(log_entry)

    await db.commit()
    await db.refresh(delivery)
    return delivery
