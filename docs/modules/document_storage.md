---
module: app/modules/document_storage/
last_updated: 2026-06-28
status: planned
---

# Module 3 – Document Storage

## Purpose
Central file store for all shipment documents. Handles upload, versioning, metadata persistence, and secure retrieval. All document-producing modules funnel through here.

## Features (from PRD)
- Supported types: PDF, JPG, PNG, DOCX, XLSX
- Upload (manual + programmatic)
- Versioning (multiple versions of same document)
- Metadata storage (source, upload date, type, shipment association)
- Secure storage (AES-256 at rest, TLS in transit)

## Exports / Public Interface
- `upload_document(file, metadata, uploaded_by)` → Document
- `get_document(document_id)` → Document + signed URL
- `list_documents(shipment_id)` → [Document]
- `add_version(document_id, file)` → DocumentVersion
- `delete_document(document_id)` → void
- `update_metadata(document_id, metadata)` → Document
- Models: `Document`, `DocumentVersion`, `DocumentMetadata`
- Events emitted: `document.uploaded` (triggers OCR + Classification pipeline)

## Depends On (imports)
| Module | Why |
|--------|-----|
| user_management | Auth + org scoping; tracks who uploaded |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| email_integration | Saves email attachments as documents |
| ocr_processing | Reads document file for text extraction |
| document_classification | Reads document for classification |
| shipment_identification | Reads document metadata for shipment matching |
| shipment_workspace | Lists and serves documents in the UI |
| ai_email_collector | Triggers upload after attachment download |

## Key Decisions / Notes
- Physical files stored in object storage (S3-compatible); DB stores metadata only
- Presigned URLs used for secure temporary access (never expose raw storage URLs)
- Documents are immutable once uploaded; new versions create new records
- `document_status` field tracks pipeline stage: `uploaded → ocr_pending → ocr_done → classified → matched`
- Org-level isolation: storage prefix keyed by org_id
