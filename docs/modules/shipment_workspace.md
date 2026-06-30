---
module: app/modules/shipment_workspace/
last_updated: 2026-06-28
status: planned
---

# Module 7 – Shipment Workspace

## Purpose
Provides the API layer for the shipment dashboard and workspace UI. Aggregates data from all other modules into a unified shipment view. Also drives the MVP dashboard widgets.

## Features (from PRD)
Shipment overview displays:
- Shipment reference
- Document list (with types, status)
- Imported emails
- Processing status
- Activity log

Dashboard widgets:
1. Total Shipments
2. Documents Imported Today
3. Unclassified Documents
4. Shipments Requiring Review
5. Recent Email Imports

## Exports / Public Interface
- `get_shipment_detail(shipment_id)` → ShipmentDetail (aggregated view)
- `list_shipments(org_id, filters, pagination)` → PaginatedShipments
- `get_dashboard_stats(org_id)` → DashboardStats
- `get_activity_log(shipment_id)` → [ActivityEntry]
- `get_recent_email_imports(org_id, limit)` → [EmailRecord]
- Models: `ShipmentDetail`, `DashboardStats`, `ActivityEntry`

## Depends On (imports)
| Module | Why |
|--------|-----|
| shipment_identification | Core shipment + document association data |
| document_storage | Document list, metadata, download URLs |
| document_classification | Document type labels shown in workspace |
| email_integration | Imported email records shown in workspace |
| user_management | Auth + role gating on workspace access |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| *(Frontend only — this is the top-level aggregation module)* | — |

## Key Decisions / Notes
- This module does NOT own data — it reads and aggregates from other modules
- All writes (reassociation, override) are delegated to the owning module
- Dashboard stats use pre-computed counters where possible (not live COUNT queries) for performance
- Activity log entries are written by individual modules (classification, matching, manual actions) and read here
- Shipments "requiring review" = any shipment with a document at `needs_review` status
