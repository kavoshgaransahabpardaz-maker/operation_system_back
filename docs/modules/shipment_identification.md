---
module: app/modules/shipment_identification/
last_updated: 2026-06-28
status: planned
---

# Module 6 – Shipment Identification

## Purpose
Extracts shipment reference numbers from document text, matches documents to existing shipments, creates new shipments when needed, and detects duplicates.

## Features (from PRD)
Identification sources:
- BL Number (Bill of Lading)
- AWB Number (Air Waybill)
- Invoice Number
- Purchase Order Number
- Container Number
- Internal Reference Number

Functions:
- Automatic shipment creation
- Automatic document association
- Duplicate detection

## Exports / Public Interface
- `identify_shipment(document_id)` → ShipmentMatchResult
- `create_shipment(org_id, references)` → Shipment
- `associate_document(document_id, shipment_id, user_id)` → void
- `reassociate_document(document_id, new_shipment_id, user_id)` → void  *(manual correction)*
- `list_shipments(org_id, filters)` → [Shipment]
- `get_shipment(shipment_id)` → Shipment
- Models: `Shipment`, `ShipmentReference`, `ShipmentMatchResult`
- Events emitted: `shipment.updated` (consumed by Shipment Workspace)

## Depends On (imports)
| Module | Why |
|--------|-----|
| ocr_processing | Reads `raw_text` to extract reference numbers |
| document_classification | Uses doc_type to pick the right extraction strategy |
| document_storage | Updates document with shipment_id association |
| user_management | Org scoping; tracks who manually reassociated |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| shipment_workspace | Core data source for shipment views and dashboards |
| ai_shipment_matcher | This module IS the implementation of the AI agent |

## Key Decisions / Notes
- Reference extraction uses regex patterns + LLM fallback for ambiguous cases
- Match strategy: find existing shipment in org by any matching reference → associate; no match → create new shipment
- Duplicate detection: if same file hash already stored under a shipment, reject + flag as duplicate
- Shipment identity is a set of references (not a single key) — a shipment can be matched by any of its references
- Manual reassociation (user correction) must be logged in the activity log
- SLA: shipment creation < 5 seconds (from PRD)
