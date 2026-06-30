---
module: app/agents/email_collector/
last_updated: 2026-06-28
status: planned
---

# AI Agent 1 – Email Collector

## Purpose
Background agent that monitors connected mailboxes, downloads attachments, and queues them into the document pipeline. Bridges Email Integration and Document Storage.

## Responsibilities (from PRD)
- Monitor mailbox for new emails
- Download attachments
- Queue documents for OCR + classification

## Exports / Public Interface
- `run_collection_job(connection_id)` → CollectionJobResult
- `handle_webhook_notification(provider, payload)` → void  *(for realtime push)*
- Models: `CollectionJobResult { emails_scanned, attachments_downloaded, errors }`

## Depends On (imports)
| Module | Why |
|--------|-----|
| email_integration | Calls sync_mailbox; reads attachment data |
| document_storage | Uploads downloaded attachments as documents |
| user_management | Service-level auth for background job execution |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| *(Scheduler / task queue — not a code module)* | Invoked on schedule or via webhook |

## Key Decisions / Notes
- Runs as an async background worker (celery/task queue)
- Scheduled every 5 minutes per connected mailbox; also triggered by push webhooks
- Errors are logged per attachment; one failure does not block the rest of the batch
- Idempotent: already-seen email message-ids are skipped
