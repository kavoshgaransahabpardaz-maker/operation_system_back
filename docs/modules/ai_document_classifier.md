---
module: app/agents/document_classifier/
last_updated: 2026-06-28
status: planned
---

# AI Agent 2 – Document Classifier

## Purpose
Background agent that listens for `ocr.completed` events and triggers document classification. Orchestrates the OCR → Classification → Shipment Matching pipeline step.

## Responsibilities (from PRD)
- Detect document type
- Estimate confidence score

## Exports / Public Interface
- `run_classification_job(document_id)` → ClassificationJobResult
- Models: `ClassificationJobResult { document_id, doc_type, confidence, success }`

## Depends On (imports)
| Module | Why |
|--------|-----|
| ocr_processing | Reads OCR result as classification input |
| document_classification | Calls classify_document(); this agent orchestrates the module |
| document_storage | Updates document pipeline status |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| *(Event bus — triggered by `ocr.completed` event)* | — |

## Key Decisions / Notes
- Triggered by `ocr.completed` event from the event bus (not a cron job)
- After classification completes, emits signal to trigger Shipment Matcher agent
- SLA: must complete within 10 seconds of receiving event (from PRD)
- Retry on transient LLM API errors (max 3 attempts with exponential backoff)
