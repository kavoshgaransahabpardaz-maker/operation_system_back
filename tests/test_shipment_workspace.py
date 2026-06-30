"""Tests for Module 7: Shipment Workspace + Dashboard (PRD §Module 7)"""
import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document_classification.models import ClassificationResult, DocumentType
from app.modules.document_storage.models import Document, DocumentSource, DocumentStatus
from app.modules.email_integration.models import EmailProvider, EmailRecord, MailboxConnection
from app.modules.shipment_identification.models import (
    ReferenceType,
    Shipment,
    ShipmentDocument,
    ShipmentReference,
    ShipmentStatus,
)
from app.modules.user_management.models import User


async def _seed_shipment_with_doc(
    db: AsyncSession,
    org_id: uuid.UUID,
    doc_type: DocumentType = DocumentType.COMMERCIAL_INVOICE,
    status: DocumentStatus = DocumentStatus.MATCHED,
) -> tuple[Shipment, Document]:
    s = Shipment(org_id=org_id, status=ShipmentStatus.ACTIVE)
    db.add(s)
    await db.flush()

    db.add(ShipmentReference(
        shipment_id=s.id, org_id=org_id,
        ref_type=ReferenceType.BL, ref_value=f"BL{uuid.uuid4().hex[:8].upper()}"
    ))

    content = uuid.uuid4().bytes
    doc = Document(
        org_id=org_id,
        filename="invoice.pdf",
        file_key="orgs/test/invoice.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        source=DocumentSource.EMAIL,
        status=status,
        shipment_id=s.id,
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(doc)
    await db.flush()

    db.add(ClassificationResult(
        document_id=doc.id,
        doc_type=doc_type,
        confidence=0.91,
        is_manual_override=False,
        classified_at=datetime.now(timezone.utc),
    ))
    db.add(ShipmentDocument(shipment_id=s.id, document_id=doc.id))

    await db.commit()
    await db.refresh(s)
    await db.refresh(doc)
    return s, doc


# ── Dashboard stats (PRD §MVP Dashboard) ─────────────────────────────────────

async def test_dashboard_returns_all_widgets(client: AsyncClient):
    r = await client.get("/api/v1/workspace/dashboard")
    assert r.status_code == 200
    data = r.json()
    # PRD requires these 5 widgets
    assert "total_shipments" in data
    assert "documents_imported_today" in data
    assert "unclassified_documents" in data
    assert "shipments_requiring_review" in data
    assert "recent_email_imports" in data


async def test_dashboard_total_shipments(client: AsyncClient, db: AsyncSession, test_user: User):
    initial_r = await client.get("/api/v1/workspace/dashboard")
    initial_count = initial_r.json()["total_shipments"]

    await _seed_shipment_with_doc(db, test_user.org_id)
    r = await client.get("/api/v1/workspace/dashboard")
    assert r.json()["total_shipments"] == initial_count + 1


async def test_dashboard_documents_imported_today(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    initial_r = await client.get("/api/v1/workspace/dashboard")
    initial_count = initial_r.json()["documents_imported_today"]

    # Upload a doc (created_at = now)
    await client.post(
        "/api/v1/documents/upload",
        files={"file": ("today.pdf", b"today content xyz 123", "application/pdf")},
    )
    r = await client.get("/api/v1/workspace/dashboard")
    assert r.json()["documents_imported_today"] >= initial_count + 1


async def test_dashboard_shipments_requiring_review(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    initial_r = await client.get("/api/v1/workspace/dashboard")
    initial_count = initial_r.json()["shipments_requiring_review"]

    # Create a shipment with a NEEDS_REVIEW document
    s, _ = await _seed_shipment_with_doc(
        db, test_user.org_id, status=DocumentStatus.NEEDS_REVIEW
    )
    r = await client.get("/api/v1/workspace/dashboard")
    assert r.json()["shipments_requiring_review"] >= initial_count + 1


async def test_dashboard_recent_email_imports(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    from app.core.security import encrypt_token

    conn = MailboxConnection(
        org_id=test_user.org_id,
        user_id=test_user.id,
        provider=EmailProvider.IMAP,
        email_address="test@imap.com",
        imap_host="imap.test.com",
        imap_port=993,
        imap_password_enc=encrypt_token("pass"),
    )
    db.add(conn)
    await db.flush()

    email = EmailRecord(
        org_id=test_user.org_id,
        connection_id=conn.id,
        message_id=f"msg-{uuid.uuid4()}",
        subject="Shipment Docs Attached",
        sender="freight@carrier.com",
        received_at=datetime.now(timezone.utc),
    )
    db.add(email)
    await db.commit()

    r = await client.get("/api/v1/workspace/dashboard")
    assert r.status_code == 200
    recent = r.json()["recent_email_imports"]
    subjects = [e["subject"] for e in recent]
    assert "Shipment Docs Attached" in subjects


# ── Shipment detail (PRD §Shipment Workspace) ─────────────────────────────────

async def test_shipment_detail_contains_all_fields(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    s, doc = await _seed_shipment_with_doc(db, test_user.org_id)
    r = await client.get(f"/api/v1/workspace/shipments/{s.id}")
    assert r.status_code == 200
    data = r.json()

    # PRD: Shipment reference
    assert "references" in data
    assert len(data["references"]) >= 1

    # PRD: Document list
    assert "documents" in data
    assert len(data["documents"]) >= 1
    doc_data = data["documents"][0]
    assert doc_data["filename"] == "invoice.pdf"
    assert doc_data["doc_type"] == "commercial_invoice"
    assert doc_data["confidence"] == pytest.approx(0.91)

    # PRD: Processing status
    assert "status" in data

    # PRD: timestamps
    assert "created_at" in data
    assert "updated_at" in data


async def test_shipment_detail_not_found(client: AsyncClient):
    r = await client.get(f"/api/v1/workspace/shipments/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_shipment_detail_wrong_org(client: AsyncClient, db: AsyncSession):
    other_org = uuid.uuid4()
    s = Shipment(org_id=other_org, status=ShipmentStatus.ACTIVE)
    db.add(s)
    await db.commit()
    r = await client.get(f"/api/v1/workspace/shipments/{s.id}")
    assert r.status_code == 404


# ── Activity log (PRD §Shipment Overview - activity log) ─────────────────────

async def test_activity_log_endpoint_exists(client: AsyncClient, db: AsyncSession, test_user: User):
    s = Shipment(org_id=test_user.org_id, status=ShipmentStatus.ACTIVE)
    db.add(s)
    await db.commit()

    r = await client.get(f"/api/v1/workspace/shipments/{s.id}/activity")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_activity_log_records_returned(client: AsyncClient, db: AsyncSession, test_user: User):
    from app.models.activity_log import ActivityAction, ActivityLog

    s = Shipment(org_id=test_user.org_id, status=ShipmentStatus.ACTIVE)
    db.add(s)
    await db.flush()

    entry = ActivityLog(
        org_id=test_user.org_id,
        shipment_id=s.id,
        actor_id=test_user.id,
        action=ActivityAction.SHIPMENT_CREATED,
        details={"info": "test"},
    )
    db.add(entry)
    await db.commit()

    r = await client.get(f"/api/v1/workspace/shipments/{s.id}/activity")
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()]
    assert "shipment_created" in actions


async def test_activity_log_limit_param(client: AsyncClient, db: AsyncSession, test_user: User):
    from app.models.activity_log import ActivityAction, ActivityLog

    s = Shipment(org_id=test_user.org_id, status=ShipmentStatus.ACTIVE)
    db.add(s)
    await db.flush()

    for _ in range(5):
        db.add(ActivityLog(
            org_id=test_user.org_id,
            shipment_id=s.id,
            action=ActivityAction.DOCUMENT_UPLOADED,
        ))
    await db.commit()

    r = await client.get(f"/api/v1/workspace/shipments/{s.id}/activity?limit=2")
    assert r.status_code == 200
    assert len(r.json()) <= 2
