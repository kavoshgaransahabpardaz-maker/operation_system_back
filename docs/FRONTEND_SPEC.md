# BrokerAI Frontend — Implementation Specification

> Hand this file to your AI agent. It contains every screen, component, API call, state shape, and routing rule needed to implement the BrokerAI frontend. Do not invent features not listed here.

---

## 1. Tech Stack

| Concern | Choice |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| Router | React Router v6 |
| Server state | TanStack Query (React Query) v5 |
| UI components | shadcn/ui (Tailwind-based) |
| Styling | Tailwind CSS v3 |
| Forms | React Hook Form + Zod |
| HTTP client | Axios (single instance with base URL + auth interceptor) |
| Icons | Lucide React |
| Date formatting | date-fns |
| Notifications | Sonner (toast library) |

---

## 2. Project Structure

```
src/
  api/               # Axios instance + typed API functions per module
    client.ts        # base axios instance + interceptors
    auth.ts
    documents.ts
    classifications.ts
    emails.ts
    shipments.ts
    workspace.ts
  components/
    layout/          # AppShell, Sidebar, TopBar
    ui/              # shadcn/ui re-exports
    shared/          # StatusBadge, FileIcon, ConfidenceBadge, EmptyState, Spinner
  features/
    auth/            # Login, Register, PasswordReset pages + forms
    dashboard/       # DashboardPage + widgets
    documents/       # DocumentListPage, DocumentDetailPage, UploadZone
    shipments/       # ShipmentListPage, ShipmentDetailPage
    email/           # EmailConnectionsPage
    settings/        # UserManagementPage
  hooks/             # useCurrentUser, useUpload, usePoll
  lib/
    utils.ts         # cn(), formatBytes(), formatDate()
    constants.ts     # STATUS_COLORS, DOC_TYPE_LABELS, etc.
  types/             # TypeScript interfaces mirroring backend schemas
  routes.tsx         # Route definitions
  main.tsx
```

---

## 3. TypeScript Types

Define these in `src/types/index.ts`.

```typescript
// ── Enums ──────────────────────────────────────────────────────────────────

export type UserRole = 'admin' | 'manager' | 'operator';

export type DocumentSource = 'email' | 'upload';

export type DocumentStatus =
  | 'uploaded'
  | 'ocr_pending'
  | 'ocr_processing'
  | 'ocr_failed'
  | 'classified'
  | 'matched'
  | 'unmatched'
  | 'needs_review';

export type DocumentType =
  | 'commercial_invoice'
  | 'packing_list'
  | 'bill_of_lading'
  | 'air_waybill'
  | 'certificate_of_origin'
  | 'insurance_certificate'
  | 'customs_declaration'
  | 'purchase_order'
  | 'delivery_order'
  | 'other';

export type EmailProvider = 'gmail' | 'microsoft365' | 'outlook' | 'imap';

export type ReferenceType = 'bl' | 'awb' | 'invoice' | 'po' | 'container' | 'internal';

export type ShipmentStatus = 'active' | 'complete' | 'on_hold';

export type ActivityAction =
  | 'document_uploaded'
  | 'document_classified'
  | 'classification_overridden'
  | 'document_matched'
  | 'document_reassociated'
  | 'shipment_created'
  | 'shipment_status_updated'
  | 'email_synced';

// ── Models ─────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  org_id: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
}

export interface Document {
  id: string;
  org_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  source: DocumentSource;
  status: DocumentStatus;
  shipment_id: string | null;
  uploaded_by: string | null;
  created_at: string;
  download_url?: string | null;
}

export interface DocumentListItem {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  source: DocumentSource;
  status: DocumentStatus;
  shipment_id: string | null;
  created_at: string;
}

export interface ClassificationResult {
  id: string;
  document_id: string;
  doc_type: DocumentType;
  confidence: number;
  is_manual_override: boolean;
  classified_by: string | null;
  classified_at: string;
}

export interface MailboxConnection {
  id: string;
  org_id: string;
  provider: EmailProvider;
  email_address: string;
  last_synced_at: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ShipmentReference {
  id: string;
  ref_type: ReferenceType;
  ref_value: string;
}

export interface Shipment {
  id: string;
  org_id: string;
  status: ShipmentStatus;
  created_at: string;
  updated_at: string;
  references: ShipmentReference[];
}

export interface DocumentSummary {
  id: string;
  filename: string;
  content_type: string;
  source: DocumentSource;
  status: DocumentStatus;
  doc_type: DocumentType | null;
  confidence: number | null;
  created_at: string;
}

export interface ShipmentDetail {
  id: string;
  org_id: string;
  status: ShipmentStatus;
  created_at: string;
  updated_at: string;
  references: ShipmentReference[];
  documents: DocumentSummary[];
}

export interface RecentEmailImport {
  id: string;
  subject: string | null;
  sender: string | null;
  provider: EmailProvider;
  received_at: string | null;
  attachment_count: number;
}

export interface DashboardStats {
  total_shipments: number;
  documents_imported_today: number;
  unclassified_documents: number;
  shipments_requiring_review: number;
  recent_email_imports: RecentEmailImport[];
}

export interface ActivityLog {
  id: string;
  action: ActivityAction;
  actor_id: string | null;
  document_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}
```

---

## 4. API Client

### `src/api/client.ts`

```typescript
import axios from 'axios';

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000',
});

// Attach JWT token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401, clear token and redirect to /login
apiClient.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('access_token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);
```

### `src/api/auth.ts`
```typescript
export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<TokenResponse>('/api/v1/auth/login', { email, password }),

  register: (data: { email: string; password: string; org_name: string; org_slug: string }) =>
    apiClient.post<User>('/api/v1/auth/register', data),

  me: () => apiClient.get<User>('/api/v1/auth/me'),

  listUsers: () => apiClient.get<User[]>('/api/v1/auth/users'),

  createUser: (data: { email: string; password: string; role?: UserRole }) =>
    apiClient.post<User>('/api/v1/auth/users', data),

  updateUser: (userId: string, data: { role?: UserRole; is_active?: boolean }) =>
    apiClient.patch<User>(`/api/v1/auth/users/${userId}`, data),

  requestPasswordReset: (email: string) =>
    apiClient.post<{ reset_token: string; message: string }>('/api/v1/auth/password-reset', { email }),

  confirmPasswordReset: (token: string, new_password: string) =>
    apiClient.post<{ status: string }>('/api/v1/auth/password-reset/confirm', { token, new_password }),
};
```

### `src/api/documents.ts`
```typescript
export const documentsApi = {
  upload: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return apiClient.post<Document>('/api/v1/documents/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  list: (shipmentId?: string) =>
    apiClient.get<DocumentListItem[]>('/api/v1/documents/', {
      params: shipmentId ? { shipment_id: shipmentId } : {},
    }),

  get: (id: string) => apiClient.get<Document>(`/api/v1/documents/${id}`),

  duplicates: (id: string) => apiClient.get<DocumentListItem[]>(`/api/v1/documents/${id}/duplicates`),
};
```

### `src/api/classifications.ts`
```typescript
export const classificationsApi = {
  get: (documentId: string) =>
    apiClient.get<ClassificationResult>(`/api/v1/classifications/${documentId}`),

  override: (documentId: string, doc_type: DocumentType) =>
    apiClient.post<ClassificationResult>(`/api/v1/classifications/${documentId}/override`, { doc_type }),
};
```

### `src/api/emails.ts`
```typescript
export const emailsApi = {
  createImap: (data: { email_address: string; imap_host: string; imap_port?: number; password: string }) =>
    apiClient.post<MailboxConnection>('/api/v1/email/connections/imap', data),

  list: () => apiClient.get<MailboxConnection[]>('/api/v1/email/connections'),

  sync: (connectionId: string) =>
    apiClient.post<{ status: string; connection_id: string }>(
      `/api/v1/email/connections/${connectionId}/sync`
    ),

  disconnect: (connectionId: string) =>
    apiClient.delete(`/api/v1/email/connections/${connectionId}`),
};
```

### `src/api/shipments.ts`
```typescript
export const shipmentsApi = {
  list: () => apiClient.get<Shipment[]>('/api/v1/shipments/'),

  get: (id: string) => apiClient.get<Shipment>(`/api/v1/shipments/${id}`),

  updateStatus: (id: string, status: ShipmentStatus) =>
    apiClient.patch<Shipment>(`/api/v1/shipments/${id}`, { status }),

  reassociateDocument: (documentId: string, shipmentId: string) =>
    apiClient.post(`/api/v1/shipments/documents/${documentId}/reassociate`, {
      shipment_id: shipmentId,
    }),
};
```

### `src/api/workspace.ts`
```typescript
export const workspaceApi = {
  dashboard: () => apiClient.get<DashboardStats>('/api/v1/workspace/dashboard'),

  shipmentDetail: (shipmentId: string) =>
    apiClient.get<ShipmentDetail>(`/api/v1/workspace/shipments/${shipmentId}`),

  activityLog: (shipmentId: string, limit = 50) =>
    apiClient.get<ActivityLog[]>(`/api/v1/workspace/shipments/${shipmentId}/activity`, {
      params: { limit },
    }),
};
```

---

## 5. Constants & Helpers

### `src/lib/constants.ts`

```typescript
export const DOC_TYPE_LABELS: Record<DocumentType, string> = {
  commercial_invoice: 'Commercial Invoice',
  packing_list: 'Packing List',
  bill_of_lading: 'Bill of Lading',
  air_waybill: 'Air Waybill',
  certificate_of_origin: 'Certificate of Origin',
  insurance_certificate: 'Insurance Certificate',
  customs_declaration: 'Customs Declaration',
  purchase_order: 'Purchase Order',
  delivery_order: 'Delivery Order',
  other: 'Other',
};

export const DOC_STATUS_LABELS: Record<DocumentStatus, string> = {
  uploaded: 'Uploaded',
  ocr_pending: 'OCR Pending',
  ocr_processing: 'Processing',
  ocr_failed: 'OCR Failed',
  classified: 'Classified',
  matched: 'Matched',
  unmatched: 'Unmatched',
  needs_review: 'Needs Review',
};

export const DOC_STATUS_COLORS: Record<DocumentStatus, string> = {
  uploaded: 'bg-gray-100 text-gray-700',
  ocr_pending: 'bg-blue-50 text-blue-700',
  ocr_processing: 'bg-blue-100 text-blue-800',
  ocr_failed: 'bg-red-100 text-red-700',
  classified: 'bg-green-100 text-green-700',
  matched: 'bg-emerald-100 text-emerald-700',
  unmatched: 'bg-orange-100 text-orange-700',
  needs_review: 'bg-yellow-100 text-yellow-800',
};

export const SHIPMENT_STATUS_LABELS: Record<ShipmentStatus, string> = {
  active: 'Active',
  complete: 'Complete',
  on_hold: 'On Hold',
};

export const SHIPMENT_STATUS_COLORS: Record<ShipmentStatus, string> = {
  active: 'bg-blue-100 text-blue-700',
  complete: 'bg-green-100 text-green-700',
  on_hold: 'bg-amber-100 text-amber-800',
};

export const REF_TYPE_LABELS: Record<ReferenceType, string> = {
  bl: 'B/L',
  awb: 'AWB',
  invoice: 'Invoice',
  po: 'PO',
  container: 'Container',
  internal: 'Internal',
};

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Admin',
  manager: 'Manager',
  operator: 'Operator',
};

export const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB
```

---

## 6. Routing

Use `createBrowserRouter` with the following route tree.

| Path | Component | Auth required | Notes |
|---|---|---|---|
| `/login` | `LoginPage` | No | Redirect to `/` if already logged in |
| `/register` | `RegisterPage` | No | |
| `/forgot-password` | `ForgotPasswordPage` | No | |
| `/reset-password` | `ResetPasswordPage` | No | reads `?token=` from query string |
| `/` | `DashboardPage` | Yes | Default route |
| `/documents` | `DocumentListPage` | Yes | |
| `/documents/:id` | `DocumentDetailPage` | Yes | |
| `/shipments` | `ShipmentListPage` | Yes | |
| `/shipments/:id` | `ShipmentDetailPage` | Yes | |
| `/email` | `EmailConnectionsPage` | Yes | |
| `/settings/users` | `UserManagementPage` | Yes | Admin only |

Wrap all authenticated routes in an `AuthGuard` component that reads `localStorage.access_token` and redirects to `/login` if missing.

---

## 7. Layout

### AppShell

All authenticated pages render inside `AppShell`:
- Fixed left `Sidebar` (240px wide)
- Top `TopBar` (user info + logout)
- Scrollable `main` content area

### Sidebar navigation items

| Icon | Label | Route | Visible to |
|---|---|---|---|
| LayoutDashboard | Dashboard | `/` | All roles |
| Files | Documents | `/documents` | All roles |
| Ship | Shipments | `/shipments` | All roles |
| Mail | Email | `/email` | All roles |
| Users | Users | `/settings/users` | Admin only |

Active route highlights with a filled background. Sidebar shows the org name at the top and a small user-role badge at the bottom.

---

## 8. Pages & Components

### 8.1 Login Page (`/login`)

**Fields**: email, password  
**Submit**: `POST /api/v1/auth/login` → store `access_token` in `localStorage` → navigate to `/`  
**Errors**: Show field-level errors from Zod, show API error message below the form  
**Links**: "Don't have an account? Register" → `/register`, "Forgot password?" → `/forgot-password`

---

### 8.2 Register Page (`/register`)

**Fields**: email, password, org name, org slug  
**Org slug**: auto-generated from org name (lowercase, hyphens) but user-editable  
**Submit**: `POST /api/v1/auth/register` → on success redirect to `/login` with success toast  
**Link**: "Already have an account? Login" → `/login`

---

### 8.3 Forgot Password Page (`/forgot-password`)

**Fields**: email  
**Submit**: `POST /api/v1/auth/password-reset`  
**On success**: Show the returned `reset_token` in a highlighted code block with a note: *"In production this is emailed to you. Copy this token to reset your password."*  
**Link**: "Back to login" → `/login`

---

### 8.4 Reset Password Page (`/reset-password`)

**Reads**: `?token=` query param (pre-fills the token field, read-only)  
**Fields**: token (read-only if from URL), new password, confirm password  
**Submit**: `POST /api/v1/auth/password-reset/confirm`  
**On success**: Toast "Password updated" → redirect to `/login`

---

### 8.5 Dashboard Page (`/`)

Calls `GET /api/v1/workspace/dashboard`. Auto-refreshes every 30 seconds via `refetchInterval`.

Layout: 4 stat cards in a 2×2 grid (desktop), then two panels below.

#### Stat Cards

| Stat | Field | Icon |
|---|---|---|
| Total Shipments | `total_shipments` | Ship |
| Imported Today | `documents_imported_today` | FileInput |
| Needs Classification | `unclassified_documents` | Tag |
| Needs Review | `shipments_requiring_review` | AlertCircle |

Show a number and a small label. `needs_review` card gets a yellow/amber background when count > 0.

#### Recent Email Imports Panel

Table/list with columns: Subject, Sender, Provider badge, Received date, Attachments count.  
Empty state: "No email imports yet. Connect a mailbox in Email settings."  
Source: `recent_email_imports` from `DashboardStats`.

#### Quick Actions Panel

Buttons:
- "Upload Document" → opens upload dialog (same as document list page upload)
- "View Documents" → navigates to `/documents`
- "Manage Email" → navigates to `/email`

---

### 8.6 Document List Page (`/documents`)

**Header**: "Documents" title + "Upload Document" button (top right)

**Upload flow**:
- Clicking "Upload Document" opens a `Dialog` containing a drag-and-drop zone
- Also shows a file input button as fallback
- Max file size: 50 MB (enforce client-side with a clear error message)
- Accepted types: `application/pdf`, `image/*`
- On file select → call `POST /api/v1/documents/upload` with `FormData`
- Show upload progress with a spinner and filename
- On success: close dialog, invalidate document list query, show toast "Document uploaded — processing started"
- On 409 conflict: show warning "This file has already been uploaded" with a link to the existing document

**Filter bar**: Status filter (All, Needs Review, Unmatched, classified) as segmented control or select.

**Document table** columns:
| Column | Notes |
|---|---|
| File | Icon + filename. Click → navigate to `/documents/:id` |
| Type | `DocumentType` label or "—" if not classified |
| Status | `StatusBadge` with color |
| Source | "Upload" or "Email" badge |
| Size | Human-readable (e.g. 1.2 MB) |
| Uploaded | Relative date (e.g. "2 hours ago") |
| Shipment | Shipment ID abbreviated (first 8 chars) or "—" |

Clicking a row navigates to `/documents/:id`.

**Pagination**: Load all (the API returns arrays, no pagination params — just show all).

**Empty state**: Upload icon + "No documents yet. Upload your first document."

---

### 8.7 Document Detail Page (`/documents/:id`)

Calls `GET /api/v1/documents/:id` and `GET /api/v1/classifications/:id` in parallel.

**Layout**: Two columns on desktop (document info left, actions right).

**Left panel — Document Info**
- Filename (large, with file type icon)
- Status badge
- Size, content type, source, uploaded date
- Shipment link (if matched): "Shipment XXXXXXXX" → navigates to `/shipments/:id`
- "Download" button → opens `download_url` in new tab

**Right panel — Classification**

If classification exists:
- Doc type label (large)
- Confidence bar: horizontal progress bar 0–100%, colored green if ≥ 70%, yellow if 50–69%, red below 50%
- Confidence percentage
- "Manual override" badge if `is_manual_override === true`
- "Override Classification" button → opens override dialog

If no classification:
- "Not yet classified" with spinner if status is `ocr_pending` or `ocr_processing`
- "Override Classification" button available regardless

**Override Classification Dialog**
- `Select` dropdown with all 10 document types
- "Save Override" button → calls `POST /api/v1/classifications/:id/override`
- On success: invalidate queries, show toast "Classification updated", close dialog

**Duplicates section** (below main panels)
- Calls `GET /api/v1/documents/:id/duplicates`
- If duplicates exist: show a warning banner "Duplicate files detected" with a list of filenames (clickable links)
- If no duplicates: hidden

**Reassociate to Shipment** (shown when `shipment_id` is null or user wants to change)
- Dropdown populated from `GET /api/v1/shipments/` — shows shipment ID + references
- "Reassociate" button → calls `POST /api/v1/shipments/documents/:id/reassociate`
- On success: reload page data, toast "Document reassociated"

---

### 8.8 Shipment List Page (`/shipments`)

Calls `GET /api/v1/shipments/`.

**Header**: "Shipments" title

**Status filter tabs**: All | Active | Complete | On Hold

**Shipment table** columns:
| Column | Notes |
|---|---|
| Shipment ID | First 8 chars of UUID. Click → `/shipments/:id` |
| References | Show up to 3 reference chips (type + value). E.g. "BL: MSKU1234" |
| Status | `ShipmentStatus` badge |
| Documents | Count is shown in the workspace detail, but here leave this blank or link to detail |
| Created | Relative date |
| Updated | Relative date |

Clicking a row navigates to `/shipments/:id`.

**Empty state**: "No shipments yet. Upload documents to start matching."

---

### 8.9 Shipment Detail Page (`/shipments/:id`)

Calls `GET /api/v1/workspace/shipments/:id` and `GET /api/v1/workspace/shipments/:id/activity`.

**Header**
- "Shipment" + short ID (first 8 chars of UUID)
- Status badge (large)
- Status update control: `Select` dropdown (Active / Complete / On Hold) → calls `PATCH /api/v1/shipments/:id` on change with confirm dialog

**References section**
- Chips/pills for each reference: type label + value. Example: `[BL: MAEU987654321]`

**Documents table**
Source: `documents` from `ShipmentDetail`.

Columns:
| Column | Notes |
|---|---|
| File | Icon + filename. Click → `/documents/:id` |
| Type | Doc type label or "—" |
| Status | Status badge |
| Confidence | Progress bar (if classified) |
| Source | Upload / Email badge |
| Date | Relative date |

**Activity Log section**
Source: `GET /api/v1/workspace/shipments/:id/activity`

Timeline list, newest first. Each entry:
- Icon per action type (see below)
- Human-readable action description (see Action Labels below)
- Relative timestamp

**Action icons & labels**:
| Action | Icon | Description |
|---|---|---|
| `document_uploaded` | Upload | "Document uploaded" |
| `document_classified` | Tag | "Document classified as {doc_type}" |
| `classification_overridden` | Edit | "Classification overridden to {doc_type}" |
| `document_matched` | Link | "Document matched to shipment" |
| `document_reassociated` | ArrowLeftRight | "Document reassociated" |
| `shipment_created` | Plus | "Shipment created" |
| `shipment_status_updated` | RefreshCw | "Status changed to {status}" |
| `email_synced` | Mail | "Email sync completed" |

Use `details` JSON from the activity log entry to fill in `{doc_type}` or `{status}` where shown.

---

### 8.10 Email Connections Page (`/email`)

Calls `GET /api/v1/email/connections`.

**Header**: "Email Connections" title + "Add Connection" button

**Connection cards** (grid, 1–3 columns):
Each card shows:
- Provider badge (IMAP / Gmail / Microsoft 365 / Outlook)
- Email address
- Last synced: relative date or "Never"
- Active status dot (green/gray)
- "Sync Now" button → calls `POST /api/v1/email/connections/:id/sync` → toast "Sync queued"
- "Disconnect" button → confirm dialog → calls `DELETE /api/v1/email/connections/:id` → toast "Disconnected" + refresh list

**Empty state**: Mail icon + "No email connections. Add one to start importing attachments automatically."

**Add IMAP Connection Dialog**
Triggered by "Add Connection" button.

Fields:
| Field | Type | Notes |
|---|---|---|
| Email address | text | |
| IMAP host | text | e.g. `imap.gmail.com` |
| IMAP port | number | Default 993 |
| Password | password | Stored encrypted on server |

Submit → `POST /api/v1/email/connections/imap`  
On success: close dialog, refresh list, toast "Mailbox connected"  
On error: show error message in dialog

---

### 8.11 User Management Page (`/settings/users`)

**Only visible and accessible to Admins.** Non-admins who navigate here should see a "403 — You don't have permission" message.

Calls `GET /api/v1/auth/users`.

**Header**: "Team Members" + "Invite User" button

**Users table** columns:
| Column | Notes |
|---|---|
| Email | |
| Role | Badge (Admin / Manager / Operator) |
| Status | Active (green dot) / Inactive (gray dot) |
| Joined | Date |
| Actions | Edit role dropdown + Deactivate/Activate toggle |

**Role edit**: Inline `Select` per row (Admin, Manager, Operator). On change → `PATCH /api/v1/auth/users/:id` with `{ role }`.

**Active toggle**: Switch per row. On toggle → `PATCH /api/v1/auth/users/:id` with `{ is_active }`.

**Invite User Dialog**:
Fields: email, password (temporary), role (default: Operator)  
Submit → `POST /api/v1/auth/users`  
On success: close dialog, refresh list, toast "User invited"

---

## 9. Shared Components

### `StatusBadge`
```
Props: { status: DocumentStatus | ShipmentStatus }
```
Renders a pill with background color from `DOC_STATUS_COLORS` or `SHIPMENT_STATUS_COLORS` and the appropriate label.

### `ConfidenceBadge`
```
Props: { confidence: number }
```
Horizontal progress bar. Color: green if ≥ 0.7, amber if 0.5–0.69, red if < 0.5. Shows percentage.

### `FileIcon`
```
Props: { contentType: string }
```
Returns a relevant Lucide icon — `FileText` for PDF, `Image` for images, `File` for others.

### `EmptyState`
```
Props: { icon: LucideIcon, title: string, description: string, action?: ReactNode }
```
Centered layout with large icon, title, description, optional action button.

### `Spinner`
Centered animated spinner. Sizes: sm / md / lg.

### `ReferenceChip`
```
Props: { ref_type: ReferenceType, ref_value: string }
```
Colored pill: type label (bold) + value. Colors per type:
- `bl` / `awb`: blue
- `invoice` / `po`: purple
- `container`: teal
- `internal`: gray

---

## 10. State Management

Use TanStack Query for all server state. Auth state is `localStorage.access_token` only — no Redux/Zustand needed.

### Query Keys

```typescript
export const queryKeys = {
  me: ['me'],
  users: ['users'],
  documents: (filters?: object) => ['documents', filters],
  document: (id: string) => ['document', id],
  classification: (docId: string) => ['classification', docId],
  duplicates: (docId: string) => ['duplicates', docId],
  shipments: ['shipments'],
  shipment: (id: string) => ['shipment', id],
  shipmentDetail: (id: string) => ['shipmentDetail', id],
  activityLog: (id: string) => ['activityLog', id],
  emailConnections: ['emailConnections'],
  dashboard: ['dashboard'],
};
```

### Refetch intervals

- `dashboard`: every 30 seconds (`refetchInterval: 30_000`)
- `document` detail: every 10 seconds when status is `ocr_pending` or `ocr_processing` (use `refetchInterval` conditionally)
- All others: default (no polling)

---

## 11. Auth Flow

1. On app start, `useCurrentUser` hook calls `GET /api/v1/auth/me` using `useQuery`.
2. If 401, the axios interceptor clears `localStorage` and redirects to `/login`.
3. On successful login, store `access_token` in `localStorage`, then navigate to `/`.
4. Logout: clear `localStorage.access_token`, call `queryClient.clear()`, navigate to `/login`.

```typescript
// src/hooks/useCurrentUser.ts
export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => authApi.me().then(r => r.data),
    retry: false,
  });
}
```

---

## 12. Error Handling

- All API errors caught in mutations/queries show a `toast.error(...)` with the API error message (`err.response?.data?.detail` or a fallback).
- Form validation errors shown inline via React Hook Form + Zod.
- 404 responses on detail pages show an inline "Not found" message, not a full-page 404.
- Loading states: all pages show a centered `<Spinner size="lg" />` while the primary query is loading.

---

## 13. Environment

`.env` file at project root:
```
VITE_API_URL=http://localhost:8000
```

---

## 14. Document Processing Status Flow

Show this lifecycle visually on `DocumentDetailPage` as a stepper or progress indicator:

```
Uploaded → OCR Pending → OCR Processing → Classified / Needs Review → Matched / Unmatched
```

If `ocr_failed`, show a red error state on the OCR step.

---

## 15. Implementation Order

Implement in this order to deliver value incrementally:

1. **Project scaffold**: Vite + React + TypeScript + Tailwind + shadcn/ui setup
2. **API client**: `src/api/client.ts` with auth interceptor
3. **Types**: `src/types/index.ts`
4. **Auth pages**: Login, Register, Forgot Password, Reset Password
5. **AppShell + Sidebar + routing skeleton**
6. **Dashboard page**
7. **Document List + Upload**
8. **Document Detail + Classification Override + Reassociate**
9. **Shipment List**
10. **Shipment Detail + Activity Log**
11. **Email Connections page**
12. **User Management page** (admin only)
13. **Polish**: empty states, loading states, error handling, responsive layout

---

## 16. Key Business Rules (enforce in UI)

- Max upload size is **50 MB**. Reject larger files client-side before calling the API.
- On a **409 Conflict** from upload, show "Duplicate file detected" and link to the existing document.
- The **"Override Classification"** button is always visible on Document Detail, even when no classification exists yet.
- Status badge colors must follow the constants defined in Section 5 — do not invent new colors.
- **Admin-only routes** (`/settings/users`): check `user.role === 'admin'` after loading `useCurrentUser`. Redirect or show a 403 message for non-admins.
- **Confidence threshold**: visually distinguish ≥ 70% (good), 50–69% (caution), < 50% (poor).
- Document detail page **polls every 10 seconds** if status is `ocr_pending` or `ocr_processing`, stops polling once status changes.
- Shipment references: render each `ref_type` + `ref_value` pair as a labeled chip — never just raw values.
