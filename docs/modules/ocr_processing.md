---
module: app/modules/ocr_processing/
last_updated: 2026-06-28
status: planned
---

# Module 4 – OCR Processing

## Purpose
Extracts raw searchable text from uploaded documents (PDFs, images, scanned files). Feeds extracted text to the classification and shipment matching pipeline.

## Features (from PRD)
- Extract text from native PDFs
- Extract text from scanned/image documents
- Detect document language
- Output: raw searchable text

## Exports / Public Interface
- `extract_text(document_id)` → OcrResult
- `get_ocr_result(document_id)` → OcrResult | None
- Models: `OcrResult { document_id, raw_text, language, confidence, processed_at }`
- Events emitted: `ocr.completed` (triggers Document Classification)

## Depends On (imports)
| Module | Why |
|--------|-----|
| document_storage | Fetches document file for processing |
| user_management | Org scoping |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| document_classification | Reads `raw_text` to classify document type |
| shipment_identification | Reads `raw_text` to extract shipment reference numbers |
| ai_document_classifier | Consumes `ocr.completed` event to trigger classification |

## Key Decisions / Notes
- For native PDFs: use PDF text extraction library first (faster, higher quality)
- For scanned/image PDFs and image files: fall back to OCR engine (e.g., Tesseract or cloud OCR)
- Language detection runs after text extraction; stored in OcrResult
- OCR results are cached — re-processing same document version is a no-op
- Processing is async: triggered by `document.uploaded` event, emits `ocr.completed` when done
- Failure handling: if OCR fails, document status set to `ocr_failed`; manual retry available
