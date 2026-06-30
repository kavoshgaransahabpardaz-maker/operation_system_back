---
module: app/agents/shipment_matcher/
last_updated: 2026-06-28
status: planned
---

# AI Agent 3 – Shipment Matcher

## Purpose
Background agent that listens for `document.classified` events and extracts shipment reference numbers from document text, then associates the document with the correct shipment (or creates a new one).

## Responsibilities (from PRD)
- Detect shipment identifiers (BL, AWB, Invoice No, PO No, Container No, Internal Ref)
- Associate documents with shipments

## Exports / Public Interface
- `run_matching_job(document_id)` → MatchingJobResult
- Models: `MatchingJobResult { document_id, shipment_id, created_new_shipment, references_found, success }`

## Depends On (imports)
| Module | Why |
|--------|-----|
| ocr_processing | Source text for reference extraction |
| document_classification | doc_type used to guide extraction (e.g., BL# extracted from BoL docs) |
| shipment_identification | Calls identify_shipment(), create_shipment(), associate_document() |
| document_storage | Updates document pipeline status |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| *(Event bus — triggered by `document.classified` event)* | — |

## Key Decisions / Notes
- Triggered by `document.classified` event from event bus
- Uses regex + LLM extraction for reference numbers; doc_type guides which patterns to try first
- SLA: shipment association < 5 seconds (from PRD)
- If no reference found: document marked `unmatched`; appears in "Unclassified Documents" dashboard widget
- Retry on transient errors (max 3 attempts)
- Emits `shipment.updated` event after successful association
