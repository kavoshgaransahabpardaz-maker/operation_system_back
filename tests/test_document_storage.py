"""Tests for Module 3: Document Storage (PRD §Module 3)"""
import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document_storage.models import Document, DocumentSource, DocumentStatus
from app.modules.document_storage import service
from app.modules.user_management.models import User


def _pdf_bytes(content: str = "test pdf content") -> bytes:
    return content.encode()


# ── Upload ────────────────────────────────────────────────────────────────────

async def test_upload_document_success(client: AsyncClient):
    r = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("invoice.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["filename"] == "invoice.pdf"
    assert data["content_type"] == "application/pdf"
    assert data["source"] == "upload"
    assert data["status"] == "uploaded"


async def test_upload_sets_content_hash(client: AsyncClient, db: AsyncSession, test_user: User):
    r = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.pdf", _pdf_bytes("unique content abc"), "application/pdf")},
    )
    assert r.status_code == 201
    doc_id = r.json()["id"]

    from sqlalchemy import select
    result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
    doc = result.scalar_one()
    assert doc.content_hash is not None
    assert len(doc.content_hash) == 64  # SHA-256 hex


async def test_upload_duplicate_rejected(client: AsyncClient):
    content = _pdf_bytes("exact same bytes for duplicate test")
    await client.post(
        "/api/v1/documents/upload",
        files={"file": ("first.pdf", content, "application/pdf")},
    )
    r2 = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("second.pdf", content, "application/pdf")},
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["detail"] == "duplicate"
    assert "existing_document_id" in r2.json()["detail"]


async def test_upload_different_content_allowed(client: AsyncClient):
    await client.post(
        "/api/v1/documents/upload",
        files={"file": ("a.pdf", _pdf_bytes("content A"), "application/pdf")},
    )
    r2 = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("b.pdf", _pdf_bytes("content B"), "application/pdf")},
    )
    assert r2.status_code == 201


async def test_upload_file_too_large(client: AsyncClient):
    big_content = b"x" * (51 * 1024 * 1024)  # 51 MB
    r = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("big.pdf", big_content, "application/pdf")},
    )
    assert r.status_code == 413


# ── List ──────────────────────────────────────────────────────────────────────

async def test_list_documents_empty(client: AsyncClient):
    r = await client.get("/api/v1/documents/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_list_documents_returns_uploaded(client: AsyncClient):
    await client.post(
        "/api/v1/documents/upload",
        files={"file": ("listed.pdf", _pdf_bytes("list test content xyz"), "application/pdf")},
    )
    r = await client.get("/api/v1/documents/")
    assert r.status_code == 200
    filenames = [d["filename"] for d in r.json()]
    assert "listed.pdf" in filenames


async def test_list_documents_filter_by_shipment(client: AsyncClient, db: AsyncSession, test_user: User):
    from app.modules.document_storage.models import Document, DocumentSource, DocumentStatus
    import hashlib

    shipment_id = uuid.uuid4()
    content = b"shipment-specific document"
    doc = Document(
        org_id=test_user.org_id,
        filename="shipment-doc.pdf",
        file_key="orgs/test/shipment-doc.pdf",
        content_type="application/pdf",
        size_bytes=len(content),
        source=DocumentSource.UPLOAD,
        status=DocumentStatus.MATCHED,
        shipment_id=shipment_id,
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(doc)
    await db.commit()

    r = await client.get(f"/api/v1/documents/?shipment_id={shipment_id}")
    assert r.status_code == 200
    assert any(d["filename"] == "shipment-doc.pdf" for d in r.json())


# ── Get single ────────────────────────────────────────────────────────────────

async def test_get_document_returns_download_url(client: AsyncClient):
    r_upload = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("getme.pdf", _pdf_bytes("get doc content 123"), "application/pdf")},
    )
    doc_id = r_upload.json()["id"]

    r = await client.get(f"/api/v1/documents/{doc_id}")
    assert r.status_code == 200
    assert r.json()["download_url"] == "https://s3.test/doc.pdf"


async def test_get_nonexistent_document(client: AsyncClient):
    r = await client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert r.status_code == 404


# ── Duplicates endpoint ───────────────────────────────────────────────────────

async def test_get_duplicates_empty_when_unique(client: AsyncClient):
    r_upload = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("unique.pdf", _pdf_bytes("unique content 999"), "application/pdf")},
    )
    doc_id = r_upload.json()["id"]
    r = await client.get(f"/api/v1/documents/{doc_id}/duplicates")
    assert r.status_code == 200
    assert r.json() == []


async def test_get_duplicates_lists_other_org_docs_separately(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    import hashlib
    shared_hash = hashlib.sha256(b"shared content xyz").hexdigest()

    # Plant two docs with the same hash in same org
    for i in range(2):
        doc = Document(
            org_id=test_user.org_id,
            filename=f"dup-{i}.pdf",
            file_key=f"orgs/test/dup-{i}.pdf",
            content_type="application/pdf",
            size_bytes=10,
            source=DocumentSource.UPLOAD,
            status=DocumentStatus.UPLOADED,
            content_hash=shared_hash,
        )
        db.add(doc)
    await db.commit()

    from sqlalchemy import select
    result = await db.execute(
        select(Document).where(
            Document.org_id == test_user.org_id,
            Document.content_hash == shared_hash,
        )
    )
    docs = result.scalars().all()
    assert len(docs) == 2

    r = await client.get(f"/api/v1/documents/{docs[0].id}/duplicates")
    assert r.status_code == 200
    # Should return the other doc as a duplicate
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == str(docs[1].id)


# ── Versioning (PRD §Document Storage) ───────────────────────────────────────

async def test_upload_creates_version_record(client: AsyncClient, db: AsyncSession, test_user: User):
    from sqlalchemy import select
    from app.modules.document_storage.models import DocumentVersion

    r = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("versioned.pdf", _pdf_bytes("versioned content abc"), "application/pdf")},
    )
    doc_id = uuid.UUID(r.json()["id"])

    result = await db.execute(
        select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
    )
    versions = result.scalars().all()
    assert len(versions) == 1
    assert versions[0].version_number == 1
