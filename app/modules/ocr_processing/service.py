"""
OCR service — runs synchronously inside Celery workers.
Uses pdfplumber for native PDFs, pytesseract for images/scanned PDFs.
"""
import io
import uuid

from sqlalchemy.orm import Session

from app.core import storage
from app.modules.document_storage.models import Document, DocumentStatus
from app.modules.ocr_processing.models import OcrResult


def _extract_from_pdf(data: bytes) -> tuple[str, float | None]:
    import pdfplumber

    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts).strip(), None


def _extract_with_ocr(data: bytes, content_type: str, lang: str = "eng") -> tuple[str, float | None]:
    import pytesseract
    from PIL import Image

    if content_type == "application/pdf":
        import pdfplumber

        images = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                img = page.to_image(resolution=200).original
                images.append(img)

        texts = [pytesseract.image_to_string(img, lang=lang) for img in images]
        return "\n".join(texts).strip(), None
    else:
        image = Image.open(io.BytesIO(data))
        text = pytesseract.image_to_string(image, lang=lang)
        return text.strip(), None


def _detect_language(text: str) -> str | None:
    if not text:
        return None
    try:
        from langdetect import detect
        return detect(text)
    except Exception:
        return None


def extract_text(db: Session, document_id: uuid.UUID, ocr_lang: str = "eng") -> OcrResult:
    doc: Document = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"Document {document_id} not found")

    existing = db.query(OcrResult).filter(OcrResult.document_id == document_id).first()
    if existing:
        return existing

    doc.status = DocumentStatus.OCR_PROCESSING
    db.commit()

    data = storage.download_bytes(doc.file_key)

    raw_text = ""
    confidence = None
    try:
        if doc.content_type == "application/pdf":
            raw_text, confidence = _extract_from_pdf(data)
            if not raw_text:
                raw_text, confidence = _extract_with_ocr(data, doc.content_type, lang=ocr_lang)
        else:
            raw_text, confidence = _extract_with_ocr(data, doc.content_type, lang=ocr_lang)

        language = _detect_language(raw_text)

        result = OcrResult(
            document_id=document_id,
            raw_text=raw_text,
            language=language,
            confidence=confidence,
        )
        db.add(result)
        doc.status = DocumentStatus.OCR_PENDING  # will be updated by classifier agent
        db.commit()
        db.refresh(result)
        return result

    except Exception as exc:
        doc.status = DocumentStatus.OCR_FAILED
        db.commit()
        raise exc
