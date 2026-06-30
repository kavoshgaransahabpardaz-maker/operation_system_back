# Module Registry

Central index of all modules/files in the project. Each module has its own detailed doc in `docs/modules/`.

**Last updated:** 2026-06-28

---

## Core Modules

| Module | Doc | Purpose | Depends On | Used By |
|--------|-----|---------|-----------|---------|
| `app/modules/user_management/` | [user_management.md](modules/user_management.md) | Auth, roles, organizations | *(none — foundational)* | All other modules |
| `app/modules/email_integration/` | [email_integration.md](modules/email_integration.md) | Connect mailboxes, sync email, extract attachments | user_management, document_storage | ai_email_collector, shipment_workspace |
| `app/modules/document_storage/` | [document_storage.md](modules/document_storage.md) | Upload, version, serve all documents securely | user_management | email_integration, ocr_processing, document_classification, shipment_identification, shipment_workspace, ai_email_collector |
| `app/modules/ocr_processing/` | [ocr_processing.md](modules/ocr_processing.md) | Extract text + language from documents | document_storage, user_management | document_classification, shipment_identification, ai_document_classifier |
| `app/modules/document_classification/` | [document_classification.md](modules/document_classification.md) | AI classification of document type + confidence | ocr_processing, document_storage, user_management | shipment_identification, shipment_workspace, ai_document_classifier |
| `app/modules/shipment_identification/` | [shipment_identification.md](modules/shipment_identification.md) | Extract refs, create/match shipments, deduplicate | ocr_processing, document_classification, document_storage, user_management | shipment_workspace, ai_shipment_matcher |
| `app/modules/shipment_workspace/` | [shipment_workspace.md](modules/shipment_workspace.md) | Aggregated API for workspace UI + dashboard stats | shipment_identification, document_storage, document_classification, email_integration, user_management | *(Frontend only)* |

---

## AI Agents

| Agent | Doc | Purpose | Depends On | Triggered By |
|-------|-----|---------|-----------|-------------|
| `app/agents/email_collector/` | [ai_email_collector.md](modules/ai_email_collector.md) | Monitor mailboxes, download attachments, queue docs | email_integration, document_storage, user_management | Scheduler (cron) + push webhooks |
| `app/agents/document_classifier/` | [ai_document_classifier.md](modules/ai_document_classifier.md) | Orchestrate OCR→Classification step | ocr_processing, document_classification, document_storage | `ocr.completed` event |
| `app/agents/shipment_matcher/` | [ai_shipment_matcher.md](modules/ai_shipment_matcher.md) | Extract refs, match/create shipments | ocr_processing, document_classification, shipment_identification, document_storage | `document.classified` event |

---

## Document Pipeline Flow

```
Email / Upload
      │
      ▼
document_storage  ──── emits: document.uploaded
      │
      ▼
ocr_processing  ──── emits: ocr.completed
      │
      ▼
document_classification  ──── emits: document.classified
      │
      ▼
shipment_identification  ──── emits: shipment.updated
      │
      ▼
shipment_workspace  (read-only aggregation → UI)
```

---

## How to Use This Registry

### When adding a new file/module:
1. Create `docs/modules/<module_name>.md` from the template below
2. Add a row to the registry table above
3. Update any modules it depends on (add this module to their "Used By" list in their doc)

### When modifying an existing file/module:
1. Check its row in this registry
2. Open its `docs/modules/<module_name>.md`
3. Review the "Used By" (dependents) list — those modules may be affected
4. After the change, update the module doc if the interface/behavior changed

### When removing a file/module:
1. Check "Used By" — fix all dependents first
2. Remove its row from this registry
3. Delete its `docs/modules/<module_name>.md`

---

## Module Doc Template

Copy this when creating a new module doc at `docs/modules/<name>.md`:

```markdown
---
module: <file path relative to project root>
last_updated: YYYY-MM-DD
status: planned | in-progress | stable
---

# <Module Name>

## Purpose
One paragraph: what this module does and why it exists.

## Exports / Public Interface
- `FunctionA(args) → return` — description
- `ClassB` — description

## Depends On (imports)
| Module | Why |
|--------|-----|
| path/to/dep | reason |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| path/to/consumer | reason |

## Key Decisions / Notes
- Any non-obvious design choices or constraints
```
