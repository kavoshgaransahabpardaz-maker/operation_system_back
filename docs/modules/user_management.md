---
module: app/modules/user_management/
last_updated: 2026-06-28
status: planned
---

# Module 1 – User Management

## Purpose
Handles all authentication, authorization, and organization/role management. Every other module gates access through this module's middleware and role checks.

## Features (from PRD)
- User registration, login, password reset
- Multi-user organizations (tenant isolation)
- Role management: Admin, Manager, Operator

## Exports / Public Interface
- `register(email, password, org_id)` → User
- `login(email, password)` → JWT token
- `reset_password(email)` → void
- `get_current_user(token)` → User
- `check_permission(user, resource, action)` → bool
- Models: `User`, `Organization`, `Role`
- Middleware: `auth_required`, `role_required(role)`

## Depends On (imports)
| Module | Why |
|--------|-----|
| *(none — foundational module)* | — |

## Used By (dependents)
| Module | How it uses this |
|--------|-----------------|
| email_integration | Auth required to connect mailboxes; org scoping |
| document_storage | Auth + role checks on upload/access |
| ocr_processing | Auth on processing requests |
| document_classification | Auth on classification triggers |
| shipment_identification | Auth + org scoping for shipment records |
| shipment_workspace | Auth + role checks on workspace access |
| ai_email_collector | Service-level auth for background jobs |
| ai_document_classifier | Service-level auth for background jobs |
| ai_shipment_matcher | Service-level auth for background jobs |

## Key Decisions / Notes
- JWT-based stateless auth
- Organization = tenant boundary; all data queries are scoped by org_id
- RBAC: Admin > Manager > Operator permission hierarchy
- Password stored as bcrypt hash (never plaintext)
- Audit log entries created for login, role changes, password resets
