---
module: app/modules/document_classification/
last_updated: 2026-06-28
status: planned
---

# Module 5 – Document Classification

## Purpose
Classifies documents into predefined customs document types using AI. Outputs document type + confidence score. Supports manual override by users.

## Features (from PRD)
Document types:
- Commercial Invoice
- Packing List
- Bill of Lading
- Air Waybill
- Certificate of Origin
- Insurance Certificate
- Customs Declaration
- Purchase Order
- Delivery Order
- Other

Output: document type + confidence score

## Exports / Public Interface
- `classify_document(document_id)` → ClassificationResult
- `override_classification(document_id, doc_type, user_id)` → ClassificationResult
- `get_classification(document_id)` → ClassificationResult | None
- Models: `ClassificationResult { document_id, doc_type, confidence, is_manual_override, classified_at, classified_by }`
- Events emitted: `document.classified` (triggers Shipment Identification)

## Depends On (imports)
| Module | Why |
|--------|-----|
| ocr_processing | Reads `raw_text` as classification input |
| document_storage | Updates document metadata with classification result |
| user_management | Tracks who performed manual override |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| shipment_identification | Uses doc_type to guide reference extraction logic |
| shipment_workspace | Displays document type in workspace UI |
| ai_document_classifier | This module IS the implementation of the AI agent |

## Key Decisions / Notes
- Classification uses LLM prompt with `raw_text` as input; returns structured JSON
- Confidence threshold: if < 70%, document flagged as `needs_review`
- Manual override always wins; stored with `is_manual_override=true`
- Manual overrides can be used as future training data
- Classification is re-run if document version changes or OCR is re-run
- SLA: < 10 seconds per document (from PRD)
