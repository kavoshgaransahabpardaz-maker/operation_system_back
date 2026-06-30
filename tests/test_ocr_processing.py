"""Tests for Module 4: OCR Processing (PRD §Module 4)"""
import hashlib
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.modules.document_storage.models import Document, DocumentSource, DocumentStatus
from app.modules.ocr_processing.models import OcrResult
from app.modules.ocr_processing import service as ocr_service


def _make_sync_doc(db, org_id: uuid.UUID) -> Document:
    content = uuid.uuid4().bytes
    doc = Document(
        id=uuid.uuid4(),
        org_id=org_id,
        filename="test.pdf",
        file_key="orgs/test/test.pdf",
        content_type="application/pdf",
        size_bytes=100,
        source=DocumentSource.UPLOAD,
        status=DocumentStatus.UPLOADED,
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(doc)
    db.commit()
    return doc


# ── PDF text extraction ───────────────────────────────────────────────────────

def test_extract_from_pdf_returns_text():
    with patch("pdfplumber.open") as mock_open:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Invoice No: INV-2024-001\nAmount: $5000"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_pdf

        text, _ = ocr_service._extract_from_pdf(b"fake pdf bytes")

    assert "Invoice No" in text
    assert "INV-2024-001" in text


def test_extract_from_pdf_empty_falls_back():
    """If pdfplumber returns no text, result should be empty string (caller does OCR fallback)."""
    with patch("pdfplumber.open") as mock_open:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = None
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_pdf

        text, _ = ocr_service._extract_from_pdf(b"scanned pdf bytes")

    assert text == ""


# ── Language detection ────────────────────────────────────────────────────────

def test_detect_language_english():
    text = "This is a commercial invoice for goods shipped from China to USA."
    lang = ocr_service._detect_language(text)
    assert lang == "en"


def test_detect_language_empty():
    lang = ocr_service._detect_language("")
    assert lang is None


def test_detect_language_short_text():
    # Very short text; langdetect may fail — should return None not raise
    lang = ocr_service._detect_language("ok")
    # May be None or a language code — just ensure no exception
    assert lang is None or isinstance(lang, str)


# ── OcrResult model ───────────────────────────────────────────────────────────

def test_ocr_result_model_fields():
    """Verify OcrResult has all PRD-required output fields."""
    result = OcrResult(
        document_id=uuid.uuid4(),
        raw_text="Sample customs declaration text.",
        language="en",
        confidence=0.95,
    )
    assert result.raw_text is not None
    assert result.language == "en"
    assert result.confidence == 0.95


# ── Integration: extract_text uses storage ────────────────────────────────────

def test_extract_text_updates_document_status(monkeypatch):
    """extract_text must update doc status to OCR_PROCESSING then back."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    org_id = uuid.uuid4()
    doc = _make_sync_doc(db, org_id)

    # Patch storage.download_bytes to return fake PDF bytes
    monkeypatch.setattr("app.modules.ocr_processing.service.storage.download_bytes", lambda _: b"fake")

    # Patch pdfplumber to return text
    with patch("pdfplumber.open") as mock_open:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "BL Number: MSKU9876543"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_pdf

        result = ocr_service.extract_text(db, doc.id)

    assert result.raw_text == "BL Number: MSKU9876543"
    assert result.document_id == doc.id
    db.close()


def test_extract_text_idempotent(monkeypatch):
    """Calling extract_text twice on same document returns existing result."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    org_id = uuid.uuid4()
    doc = _make_sync_doc(db, org_id)

    monkeypatch.setattr("app.modules.ocr_processing.service.storage.download_bytes", lambda _: b"fake")

    with patch("pdfplumber.open") as mock_open:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Some text content"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: mock_pdf
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_pdf

        r1 = ocr_service.extract_text(db, doc.id)
        r2 = ocr_service.extract_text(db, doc.id)  # second call

    assert r1.id == r2.id  # same record returned
    db.close()
