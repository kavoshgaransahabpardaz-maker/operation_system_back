---
module: app/modules/email_integration/
last_updated: 2026-06-28
status: planned
---

# Module 2 – Email Integration

## Purpose
Connects user/org email accounts (Gmail, M365, Outlook, IMAP) via OAuth or credentials, synchronizes mailboxes, and extracts attachments into the document pipeline.

## Features (from PRD)
- OAuth authentication for Gmail and Microsoft 365
- IMAP support for generic mailboxes
- Incremental sync (polling or push via webhooks)
- Historical email import
- Attachment extraction → hands off to Document Storage
- Captures: Subject, Sender, Recipient, Date, Attachments

## Exports / Public Interface
- `connect_mailbox(user_id, provider, credentials)` → MailboxConnection
- `disconnect_mailbox(connection_id)` → void
- `sync_mailbox(connection_id)` → SyncResult
- `list_connections(org_id)` → [MailboxConnection]
- Models: `MailboxConnection`, `EmailRecord`, `EmailAttachment`
- Events emitted: `attachment.received` (triggers AI Email Collector agent)

## Depends On (imports)
| Module | Why |
|--------|-----|
| user_management | Auth + org scoping for mailbox connections |
| document_storage | Saves extracted attachments as documents |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| ai_email_collector | Triggered by `attachment.received` events |
| shipment_workspace | Displays imported emails in shipment activity log |

## Key Decisions / Notes
- OAuth tokens stored encrypted (AES-256), refreshed automatically
- IMAP passwords stored encrypted; never logged
- Sync runs on a schedule (e.g., every 5 min) per mailbox connection
- Deduplication: email message-id used to prevent re-importing same email
- Webhook support for Gmail (Pub/Sub) and M365 (Graph API change notifications) for near-realtime sync
- Attachment size limit enforced before storage (configurable, default 50MB)
