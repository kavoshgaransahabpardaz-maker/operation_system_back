"""
End-to-end pipeline tests: Upload → OCR → Classify → Match
These test the full document processing pipeline described in the PRD.
"""
import hashlib
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document_storage.models import Document, DocumentSource, DocumentStatus
from app.modules.document_classification.models import ClassificationResult, DocumentType
from app.modules.ocr_processing.models import OcrResult
from app.modules.shipment_identification.models import Shipment, ShipmentDocument
from app.modules.user_management.models import User


def _sync_db():
    """Create an in-memory SQLite sync session for Celery service tests."""
    from app.core.database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _make_doc_sync(db, org_id: uuid.UUID, status=DocumentStatus.UPLOADED) -> Document:
    content = uuid.uuid4().bytes
    doc = Document(
        id=uuid.uuid4(),
        org_id=org_id,
        filename="shipment-doc.pdf",
        file_key="orgs/test/shipment-doc.pdf",
        content_type="application/pdf",
        size_bytes=200,
        source=DocumentSource.UPLOAD,
        status=status,
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(doc)
    db.commit()
    return doc


# ── Upload triggers pipeline ──────────────────────────────────────────────────

async def test_upload_queues_ocr_task(client: AsyncClient, mock_celery):
    """Uploading a document must queue the OCR+classify Celery task."""
    r = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.pdf", b"pipeline test content abc", "application/pdf")},
    )
    assert r.status_code == 201
    # Celery task should have been called (mock_celery fixture)
    from app.agents.document_classifier import tasks as clf_tasks
    clf_tasks.run_ocr_then_classify.apply_async.assert_called_once()


# ── OCR → Classification pipeline ────────────────────────────────────────────

def test_ocr_service_then_classification_service(monkeypatch):
    """
    Full sync pipeline: extract_text → classify_document
    Uses mocked pdfplumber and OpenAI.
    """
    from app.modules.ocr_processing.service import extract_text
    from app.modules.document_classification.service import classify_document

    db = _sync_db()
    org_id = uuid.uuid4()
    doc = _make_doc_sync(db, org_id)

    # Mock S3 download
    monkeypatch.setattr(
        "app.modules.ocr_processing.service.storage.download_bytes",
        lambda _: b"fake pdf bytes",
    )

    # Mock pdfplumber extraction
    with patch("pdfplumber.open") as mock_open:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "COMMERCIAL INVOICE\n"
            "Invoice No: INV-2024-999\n"
            "From: Supplier Co\n"
            "To: Buyer Corp\n"
            "Total: USD 15,000"
        )
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_pdf

        ocr_result = extract_text(db, doc.id)

    assert "COMMERCIAL INVOICE" in ocr_result.raw_text
    assert "INV-2024-999" in ocr_result.raw_text

    # Mock OpenAI classification
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(
        {"doc_type": "commercial_invoice", "confidence": 0.97}
    )
    with patch("openai.OpenAI") as MockOAI:
        MockOAI.return_value.chat.completions.create.return_value = mock_response
        cls_result = classify_document(db, doc.id)

    assert cls_result.doc_type == DocumentType.COMMERCIAL_INVOICE
    assert cls_result.confidence == pytest.approx(0.97)
    assert cls_result.is_manual_override is False

    # Doc status should be CLASSIFIED (confidence > 0.70)
    db.refresh(doc)
    assert doc.status == DocumentStatus.CLASSIFIED
    db.close()


def test_low_confidence_sets_needs_review(monkeypatch):
    """Documents with confidence < 0.70 must be marked NEEDS_REVIEW."""
    from app.modules.ocr_processing.service import extract_text
    from app.modules.document_classification.service import classify_document

    db = _sync_db()
    org_id = uuid.uuid4()
    doc = _make_doc_sync(db, org_id)

    monkeypatch.setattr(
        "app.modules.ocr_processing.service.storage.download_bytes",
        lambda _: b"ambiguous content",
    )

    with patch("pdfplumber.open") as mock_open:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Some unrecognizable content"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_pdf
        extract_text(db, doc.id)

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(
        {"doc_type": "other", "confidence": 0.45}  # below 0.70 threshold
    )
    with patch("openai.OpenAI") as MockOAI:
        MockOAI.return_value.chat.completions.create.return_value = mock_response
        classify_document(db, doc.id)

    db.refresh(doc)
    assert doc.status == DocumentStatus.NEEDS_REVIEW
    db.close()


# ── Classification → Shipment Matching pipeline ───────────────────────────────

def test_shipment_matcher_regex_match(monkeypatch):
    """Shipment matcher finds container number via regex and creates shipment."""
    from app.modules.shipment_identification.service import identify_and_associate

    db = _sync_db()
    org_id = uuid.uuid4()
    doc = _make_doc_sync(db, org_id, status=DocumentStatus.CLASSIFIED)

    # Plant OCR result with a container number
    ocr = OcrResult(
        document_id=doc.id,
        raw_text=(
            "PACKING LIST\n"
            "Container: MSCU1234567\n"
            "Shipper: ABC Corp\n"
            "Port of Loading: Shanghai"
        ),
        language="en",
    )
    db.add(ocr)
    db.commit()

    shipment = identify_and_associate(db, doc.id)

    assert shipment is not None
    assert shipment.org_id == org_id

    db.refresh(doc)
    assert doc.status == DocumentStatus.MATCHED
    assert doc.shipment_id == shipment.id

    # ShipmentDocument association must exist
    assoc = db.query(ShipmentDocument).filter(
        ShipmentDocument.document_id == doc.id,
        ShipmentDocument.shipment_id == shipment.id,
    ).first()
    assert assoc is not None
    db.close()


def test_shipment_matcher_no_refs_marks_unmatched(monkeypatch):
    """Documents with no extractable references are marked UNMATCHED."""
    from app.modules.shipment_identification.service import identify_and_associate

    db = _sync_db()
    org_id = uuid.uuid4()
    doc = _make_doc_sync(db, org_id, status=DocumentStatus.CLASSIFIED)

    ocr = OcrResult(
        document_id=doc.id,
        raw_text="Random text with no shipping references at all.",
        language="en",
    )
    db.add(ocr)
    db.commit()

    # Mock OpenAI LLM fallback to return empty
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({})
    with patch("openai.OpenAI") as MockOAI:
        MockOAI.return_value.chat.completions.create.return_value = mock_response
        result = identify_and_associate(db, doc.id)

    assert result is None
    db.refresh(doc)
    assert doc.status == DocumentStatus.UNMATCHED
    db.close()


def test_shipment_matcher_deduplicates_document(monkeypatch):
    """
    Document already associated with a shipment must not create a duplicate ShipmentDocument row.
    """
    from app.modules.shipment_identification.service import identify_and_associate

    db = _sync_db()
    org_id = uuid.uuid4()
    doc = _make_doc_sync(db, org_id, status=DocumentStatus.CLASSIFIED)

    ocr = OcrResult(
        document_id=doc.id,
        raw_text="Container: TCKU3453489",
        language="en",
    )
    db.add(ocr)
    db.commit()

    # First call — creates shipment and association
    shipment1 = identify_and_associate(db, doc.id)
    # Second call — should reuse existing, NOT create duplicate
    shipment2 = identify_and_associate(db, doc.id)

    assert shipment1.id == shipment2.id

    assoc_count = db.query(ShipmentDocument).filter(
        ShipmentDocument.document_id == doc.id
    ).count()
    assert assoc_count == 1
    db.close()


def test_second_doc_with_same_ref_joins_existing_shipment():
    """Two documents sharing a BL number must land in the same shipment."""
    from app.modules.shipment_identification.service import identify_and_associate

    db = _sync_db()
    org_id = uuid.uuid4()

    doc1 = _make_doc_sync(db, org_id, status=DocumentStatus.CLASSIFIED)
    doc2 = _make_doc_sync(db, org_id, status=DocumentStatus.CLASSIFIED)

    bl_text = "BILL OF LADING\nBL NO: MAEU987654321"

    for doc in [doc1, doc2]:
        ocr = OcrResult(document_id=doc.id, raw_text=bl_text, language="en")
        db.add(ocr)
        db.commit()

    s1 = identify_and_associate(db, doc1.id)
    s2 = identify_and_associate(db, doc2.id)

    assert s1 is not None
    assert s2 is not None
    assert s1.id == s2.id, "Both documents must be in the same shipment"
    db.close()


# ── Health check ──────────────────────────────────────────────────────────────

async def test_health_endpoint(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
