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
    fields.ts        # extracted field review
    flags.ts         # mismatch flags
    orgSettings.ts   # tolerance settings
    intel.ts         # NEW — trade intelligence feed, search, interests, alerts
  components/
    layout/          # AppShell, Sidebar, TopBar
    ui/              # shadcn/ui re-exports
    shared/          # StatusBadge, FileIcon, ConfidenceBadge, EmptyState, Spinner
  features/
    auth/            # Login, Register, PasswordReset pages + forms
    dashboard/       # DashboardPage + widgets
    documents/       # DocumentListPage, DocumentDetailPage, UploadZone
    shipments/       # ShipmentListPage, ShipmentDetailPage
    fields/          # FieldReviewPanel, FieldRow, CorrectFieldDialog
    flags/           # FlagListPanel, FlagCard, ResolveFlagDialog, SuggestionsPanel (NEW)
    intel/           # NEW — IntelFeedPage, IntelSearchPage, IntelArticlePage, IntelInterestsPanel, AlertsPanel
    email/           # EmailConnectionsPage
    settings/        # UserManagementPage, OrgSettingsPage (NEW)
  hooks/             # useCurrentUser, useUpload, usePoll
  lib/
    utils.ts         # cn(), formatBytes(), formatDate()
    constants.ts     # STATUS_COLORS, DOC_TYPE_LABELS, FIELD_NAME_LABELS, etc.
  types/             # TypeScript interfaces mirroring backend schemas
  routes.tsx         # Route definitions
  main.tsx
```

---

## 3. TypeScript Types

Define these in `src/types/index.ts`.

```typescript
// ── Enums ──────────────────────────────────────────────────────────────────

export type UserRole = 'super_admin' | 'admin' | 'manager' | 'operator';

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
  | 'mill_certificate'        // NEW
  | 'suppliers_declaration'   // NEW
  | 'cmr'                          // NEW — CMR consignment note
  | 'phytosanitary_certificate'    // NEW — plant health certificate
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
  | 'email_synced'
  | 'field_extracted'
  | 'field_confirmed'
  | 'field_corrected'
  | 'flag_created'
  | 'flag_resolved'
  | 'comparison_run'
  | 'settings_updated';

// ── NEW: Field extraction ──────────────────────────────────────────────────

export type FieldName =
  // ── Parties ──────────────────────────────────────────────────────────────
  | 'party_shipper'                  // seller / consignor full name + address
  | 'party_consignee'                // buyer / consignee full name + address
  | 'vat_number_seller'              // seller VAT / EIK (BG) / TVA etc.
  | 'vat_number_buyer'               // buyer VAT number
  | 'rex_number_seller'              // seller Registered Exporter number
  | 'rex_number_buyer'               // buyer REX number
  | 'eori_number'                    // EORI (2-letter country + digits)
  // ── Financials ───────────────────────────────────────────────────────────
  | 'invoice_value'
  | 'vat_value'                      // VAT amount (CI)
  | 'freight_value'                  // freight cost (PL)
  | 'insurance_value'                // insurance cost (PL)
  | 'currency'
  // ── Weights & measures ───────────────────────────────────────────────────
  | 'gross_weight'
  | 'net_weight'
  | 'quantity'
  | 'total_packages'                 // total package count (PL)
  // ── Product ──────────────────────────────────────────────────────────────
  | 'hs_code'
  | 'commodity_description'
  | 'lot_number'
  | 'product_registration_number'
  | 'product_serial_number'
  // ── Trade terms & compliance ─────────────────────────────────────────────
  | 'stated_origin'
  | 'destination_country'
  | 'place_of_loading'
  | 'incoterm'
  | 'preferential_duty'              // self-certification statement text or "yes"
  // ── Dates ────────────────────────────────────────────────────────────────
  | 'invoice_date'
  | 'due_date'                       // payment due date (CI)
  | 'shipment_date'
  | 'expiry_date'                    // product / certificate expiry
  // ── Identifiers ──────────────────────────────────────────────────────────
  | 'reference'
  | 'local_reference'                // phytosanitary NPPO reference
  | 'point_of_entry';                // phytosanitary port / border entry

export type FieldStatus = 'extracted' | 'confirmed' | 'corrected';

export type FieldType = 'string' | 'decimal' | 'date' | 'iso_code';

export interface ExtractedField {
  id: string;
  document_id: string;
  shipment_id: string | null;
  org_id: string;
  field_name: FieldName;
  value_raw: string;
  value_normalized: string | null;
  field_type: FieldType;
  confidence: number;           // 0.0 – 1.0
  page_number: number | null;
  status: FieldStatus;
  confirmed_at: string | null;
  confirmed_by: string | null;
  corrected_value: string | null;
  corrected_by: string | null;
  corrected_at: string | null;
  created_at: string;
}

// ── NEW: Flags & mismatches ────────────────────────────────────────────────

export type FlagType =
  | 'missing_document'
  | 'missing_field'
  | 'mismatch'
  | 'low_confidence'
  | 'hs_inconsistency';

export type FlagSeverity = 'critical' | 'warning' | 'info';

export type FlagStatus = 'open' | 'resolved';

export type FlagDecision = 'accepted' | 'overridden' | 'dismissed';

export interface ConflictingValue {
  document_id: string;
  field_name: FieldName;
  value_raw: string;
  page_number: number | null;
}

export interface Flag {
  id: string;
  shipment_id: string;
  org_id: string;
  flag_type: FlagType;
  severity: FlagSeverity;
  title: string;
  description: string;
  conflicting_values: ConflictingValue[] | null;
  status: FlagStatus;
  created_at: string;
  resolved_at: string | null;
}

export interface FlagResolution {
  id: string;
  flag_id: string;
  resolved_by: string;
  decision: FlagDecision;
  chosen_value: string | null;
  note: string | null;
  created_at: string;
}

// ── NEW: Org settings ──────────────────────────────────────────────────────

export interface OrgSettings {
  id: string;
  org_id: string;
  weight_qty_tolerance_pct: number;   // default 0.5 (= 0.5%)
  value_tolerance_pct: number;        // default 1.0 (= 1.0%)
  name_match_threshold: number;       // default 0.93 (= 93%)
  doc_organization_by: 'shipment' | 'client' | 'lane' | 'date';  // default 'shipment'
  auto_fix_threshold: number;         // 0.5–1.0, default 0.95
  email_critical_alerts: boolean;     // default true
  created_at: string;
  updated_at: string;
}

// ── Existing models ────────────────────────────────────────────────────────

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

// ── NEW: Suggestions ───────────────────────────────────────────────────────

export interface Suggestion {
  field_name: FieldName;
  suggested_value: string;
  cited_document_ids: string[];
  rationale: string;
}

// ── NEW: Attention queue (enhanced dashboard) ──────────────────────────────

export interface AttentionShipment {
  id: string;
  short_id: string;   // first 8 chars of UUID
  flag_count: number;
}

// ── NEW: Trade Intelligence ────────────────────────────────────────────────

export type IntelEventType =
  | 'tariff_change'
  | 'sanctions'
  | 'regulation'
  | 'trade_agreement'
  | 'market_notice'
  | 'other';

export type InterestType = 'hs_chapter' | 'hs_heading' | 'hs_code' | 'country' | 'party_name' | 'industry';

export type AlertDeliveryType = 'email';

export type AlertDeliveryStatus = 'sent' | 'failed';

export interface IntelEnrichment {
  id: string;
  article_id: string;
  summary: string | null;          // ≤80 words
  event_type: IntelEventType | null;
  countries: string[] | null;      // ISO country codes
  hs_chapters: string[] | null;
  hs_headings: string[] | null;
  regulation_refs: string[] | null;
  impact_score: number | null;     // 1–5
  impact_rationale: string | null;
  model_version: string;
  enriched_at: string;
  // Extended fields
  industries: string[] | null;
  companies: string[] | null;
  commodities: string[] | null;
  topics: string[] | null;
  trade_agreements: string[] | null;
  ports: string[] | null;
  currencies: string[] | null;
  severity: string | null;         // low / medium / high / critical
  urgency: string | null;          // immediate / short_term / long_term
  supply_chain_impact: string | null;
  price_effect: string | null;     // increase / decrease / neutral / unknown
  affected_industries: string[] | null;
  affected_countries: string[] | null;
}

export interface IntelMatch {
  id: string;
  article_id: string;
  shipment_id: string | null;
  org_id: string;
  match_reason: string;            // "HS 7208 ∩ your product records"
  match_score: number | null;
  created_at: string;
}

export interface IntelFeedItem {
  article: IntelArticle;
  enrichment: IntelEnrichment | null;
  matches: IntelMatch[];
  match_reason: string | null;     // top match reason for this org
}

export interface IntelArticle {
  id: string;
  source_id: string;
  url: string | null;
  title: string;
  content_raw: string;
  published_at: string | null;
  ingested_at: string;
  language: string | null;         // ISO language code e.g. "en"
  author: string | null;
  image_url: string | null;
  word_count: number | null;
  is_duplicate: boolean;
  processing_status: 'raw' | 'parsed' | 'enriched' | 'failed';
}

export interface IntelSource {
  id: string;
  name: string;
  source_type: string | null;      // rss / scraper / api / sanctions_list
  category: string | null;         // tariff / sanctions / regulation / trade_news
  url: string;
  poll_cadence_minutes: number;
  is_active: boolean;
  last_polled_at: string | null;
  last_error: string | null;
  health_status: string;           // unknown / healthy / degraded / dead
  articles_collected: number;
  priority: number;                // lower = polled first
  config: Record<string, unknown> | null;
  created_at: string;
}

export interface IntelJob {
  id: string;
  source_id: string | null;
  job_type: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  articles_processed: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface TrendingTopic {
  id: string;
  topic: string;
  topic_type: string;              // hs_chapter / country / event_type / commodity
  article_count: number;
  period_start: string;            // YYYY-MM-DD
  period_end: string;
  created_at: string;
}

export interface KnowledgeRelation {
  id: string;
  subject_type: string;            // country / hs_code / company / regulation
  subject_value: string;
  predicate: string;               // affects / references / applies_to / etc.
  object_type: string;
  object_value: string;
  article_id: string | null;
  confidence: number;              // 0.0–1.0
  created_at: string;
}

export interface NotificationPreference {
  id: string;
  org_id: string;
  user_id: string;
  min_impact_score: number;        // 1–5; articles below this are not alerted
  event_types: IntelEventType[];   // empty = all event types
  delivery_channels: ('email')[];  // in_app removed — only email delivery supported
  is_active: boolean;
  created_at: string;
}

// ── NEW: Article feedback ──────────────────────────────────────────────────

export interface ArticleFeedback {
  id: string;
  article_id: string;
  user_id: string;
  feedback: 'like' | 'dislike';
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface MyFeedback {
  feedback: 'like' | 'dislike' | null;
  comment: string | null;
}

// ── NEW: Interest type catalogue ───────────────────────────────────────────

export interface InterestTypeOption {
  type: InterestType;
  label: string;
  description: string;
  example: string;
  format_hint: string;
}

// ── NEW: Source preference per org ────────────────────────────────────────

export interface OrgSourcePreference {
  id: string;
  source_id: string;
  source_name: string;
  is_enabled: boolean;
  created_at: string;
}

// ── NEW: Feed filter options ───────────────────────────────────────────────

export interface ImpactLevel {
  level: number;           // 1–5
  label: string;
  description: string;
}

export interface EventTypeOption {
  value: IntelEventType;
  label: string;
  description: string;
}

export interface FilterOptions {
  countries: string[];             // ISO alpha-2 codes seen in recent articles
  industries: string[];
  event_types: EventTypeOption[];
  impact_scale: ImpactLevel[];
}

// ── NEW: Personalized summary ──────────────────────────────────────────────

export interface PersonalizedSummary {
  article_id: string;
  summary: string;                 // AI summary tailored to org interests
  relevant_interests: string[];    // which interests matched
  general_summary: string | null;  // original enrichment summary for comparison
}

export interface HeatmapEntry {
  country: string;                 // ISO country code
  article_count: number;
}

export interface EventTypeCount {
  event_type: IntelEventType;
  article_count: number;
}

export interface ImpactTimelineEntry {
  date: string;                    // YYYY-MM-DD
  avg_impact_score: number;
  article_count: number;
}

export interface SearchResult {
  article_id: string;
  title: string;
  url: string | null;
  published_at: string | null;
  ingested_at: string | null;
  processing_status: string;
  rank: number;                    // FTS rank score
  match_source: string;            // 'fts' | 'tag'
}

export interface UserInterest {
  id: string;
  org_id: string;
  interest_type: InterestType;
  value: string;
  is_explicit: boolean;            // false = auto-seeded from history
  created_at: string;
}

export interface AlertDelivery {
  id: string;
  org_id: string;
  article_id: string | null;
  delivery_type: AlertDeliveryType;
  subject: string | null;
  body_summary: string | null;
  delivered_at: string;
  status: AlertDeliveryStatus;
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
  // Sign in with Google — sends Google ID token, receives our JWT
  googleLogin: (credential: string) =>
    apiClient.post<TokenResponse>('/api/v1/auth/google', { credential }),

  // Create a new org + admin using Google ID token
  registerWithGoogle: (data: { credential: string; org_name: string; org_slug: string }) =>
    apiClient.post<User>('/api/v1/auth/register-with-google', data),

  me: () => apiClient.get<User>('/api/v1/auth/me'),

  listUsers: () => apiClient.get<User[]>('/api/v1/auth/users'),

  // Invite a user — they sign in via Google using this email
  createUser: (data: { email: string; role?: UserRole }) =>
    apiClient.post<User>('/api/v1/auth/users', data),

  updateUser: (userId: string, data: { role?: UserRole; is_active?: boolean }) =>
    apiClient.patch<User>(`/api/v1/auth/users/${userId}`, data),
};
```

**Note on role change**: `authApi.updateUser(userId, { role })` handles role promotion/demotion. Admin cannot change their own role — enforce this client-side by disabling the dropdown when `userId === currentUser.id`.

**NPM package required**: `@react-oauth/google` — Google's official React Sign-In button.

```bash
npm install @react-oauth/google
```

Wrap the app root in `<GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID}>`.

```
# .env
VITE_API_URL=http://localhost:8000
VITE_GOOGLE_CLIENT_ID=<your Google OAuth 2.0 client ID>
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

  // Upload up to 15 files in one request (max 1 GB each)
  uploadBatch: (files: File[]) => {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    return apiClient.post<Document[]>('/api/v1/documents/upload/batch', fd, {
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

  // keywords: null means "no filter"; pass array to restrict to those subjects
  updateKeywords: (connectionId: string, keywords: string[] | null) =>
    apiClient.patch<MailboxConnection>(
      `/api/v1/email/connections/${connectionId}/keywords`,
      { keywords }
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

### `src/api/fields.ts` — NEW
```typescript
export const fieldsApi = {
  // All extracted fields for a shipment (across all documents)
  listByShipment: (shipmentId: string) =>
    apiClient.get<ExtractedField[]>(`/api/v1/shipments/${shipmentId}/fields`),

  // Fields extracted from a single document
  listByDocument: (documentId: string) =>
    apiClient.get<ExtractedField[]>(`/api/v1/documents/${documentId}/fields`),

  // User confirms the extracted value is correct
  confirm: (fieldId: string) =>
    apiClient.post<ExtractedField>(`/api/v1/fields/${fieldId}/confirm`),

  // User provides a corrected value
  correct: (fieldId: string, corrected_value: string) =>
    apiClient.post<ExtractedField>(`/api/v1/fields/${fieldId}/correct`, { corrected_value }),
};
```

### `src/api/flags.ts` — NEW
```typescript
export const flagsApi = {
  // List flags for a shipment. Optional filter: status=open|resolved
  listByShipment: (shipmentId: string, status?: 'open' | 'resolved') =>
    apiClient.get<Flag[]>(`/api/v1/shipments/${shipmentId}/flags`, {
      params: status ? { status } : {},
    }),

  // Resolve a flag
  resolve: (flagId: string, data: { decision: FlagDecision; chosen_value?: string; note?: string }) =>
    apiClient.post<Flag>(`/api/v1/flags/${flagId}/resolve`, data),
};
```

### `src/api/orgSettings.ts`
```typescript
export const orgSettingsApi = {
  get: () => apiClient.get<OrgSettings>('/api/v1/org/settings'),

  update: (data: Partial<Pick<OrgSettings,
    | 'weight_qty_tolerance_pct'
    | 'value_tolerance_pct'
    | 'name_match_threshold'
    | 'doc_organization_by'
    | 'auto_fix_threshold'
    | 'email_critical_alerts'
    | 'ocr_languages'
  >>) => apiClient.patch<OrgSettings>('/api/v1/org/settings', data),
};
```

### `src/api/intel.ts` — NEW
```typescript
export const intelApi = {
  // Personalised feed — articles matched to the org's interests/shipments first
  feed: (params?: {
    limit?: number;
    offset?: number;
    event_type?: IntelEventType;
    min_impact?: number;
    country?: string;        // ISO alpha-2
    industry?: string;
    matched_only?: boolean;
  }) =>
    apiClient.get<IntelFeedItem[]>('/api/v1/intel/feed', { params }),

  // Full-text keyword search over articles
  search: (q: string, limit = 20) =>
    apiClient.get<IntelFeedItem[]>('/api/v1/intel/search', { params: { q, limit } }),

  // Single article detail
  article: (articleId: string) =>
    apiClient.get<IntelFeedItem>(`/api/v1/intel/articles/${articleId}`),

  // Articles matched to a specific shipment
  shipmentIntel: (shipmentId: string) =>
    apiClient.get<IntelFeedItem[]>(`/api/v1/shipments/${shipmentId}/intel`),

  // Interest profile
  listInterests: () => apiClient.get<UserInterest[]>('/api/v1/intel/interests'),

  addInterest: (data: { interest_type: InterestType; value: string }) =>
    apiClient.post<UserInterest>('/api/v1/intel/interests', data),

  deleteInterest: (interestId: string) =>
    apiClient.delete(`/api/v1/intel/interests/${interestId}`),

  // Alerts
  listAlerts: (limit = 50) =>
    apiClient.get<AlertDelivery[]>('/api/v1/intel/alerts', { params: { limit } }),

  // Tags autocomplete for search UI
  tagsAutocomplete: (prefix: string) =>
    apiClient.get<string[]>('/api/v1/intel/tags/autocomplete', { params: { prefix } }),

  // Notification preferences
  getNotificationPreferences: () =>
    apiClient.get<NotificationPreference>('/api/v1/intel/notifications/preferences'),

  updateNotificationPreferences: (data: Partial<Pick<NotificationPreference, 'min_impact_score' | 'event_types' | 'delivery_channels' | 'is_active'>>) =>
    apiClient.patch<NotificationPreference>('/api/v1/intel/notifications/preferences', data),

  // Analytics
  trendingTopics: (params?: { limit?: number; topic_type?: string }) =>
    apiClient.get<TrendingTopic[]>('/api/v1/intel/analytics/trending', { params }),

  countryHeatmap: (days = 30) =>
    apiClient.get<HeatmapEntry[]>('/api/v1/intel/analytics/heatmap', { params: { days } }),

  byEventType: (days = 30) =>
    apiClient.get<EventTypeCount[]>('/api/v1/intel/analytics/by-event-type', { params: { days } }),

  impactTimeline: (days = 30) =>
    apiClient.get<ImpactTimelineEntry[]>('/api/v1/intel/analytics/impact-timeline', { params: { days } }),

  // Knowledge graph
  knowledgeGraph: (subjectType: string, subjectValue: string) =>
    apiClient.get<KnowledgeRelation[]>('/api/v1/intel/knowledge-graph', {
      params: { subject_type: subjectType, subject_value: subjectValue },
    }),

  // Admin — source management
  listSources: () => apiClient.get<IntelSource[]>('/api/v1/intel/sources'),

  createSource: (data: {
    name: string; source_type?: string; category?: string;
    url: string; poll_cadence_minutes?: number; is_active?: boolean;
    priority?: number; config?: Record<string, unknown>;
  }) => apiClient.post<IntelSource>('/api/v1/intel/sources', data),

  updateSource: (sourceId: string, data: Partial<IntelSource>) =>
    apiClient.patch<IntelSource>(`/api/v1/intel/sources/${sourceId}`, data),

  deactivateSource: (sourceId: string) =>
    apiClient.delete(`/api/v1/intel/sources/${sourceId}`),

  pollSource: (sourceId: string) =>
    apiClient.post<{ status: string; source_id: string; source_name: string }>(
      `/api/v1/intel/sources/${sourceId}/poll`
    ),

  // Admin — jobs
  listJobs: (params?: { limit?: number; status?: string; job_type?: string }) =>
    apiClient.get<IntelJob[]>('/api/v1/intel/jobs', { params }),

  // Admin — reprocess
  reprocessArticle: (articleId: string) =>
    apiClient.post<{ status: string; article_id: string; title: string }>(
      `/api/v1/intel/admin/reprocess/${articleId}`
    ),

  // Feed filter options (countries, industries, event types, impact scale)
  getFilterOptions: () =>
    apiClient.get<FilterOptions>('/api/v1/intel/filter-options'),

  // Article feedback — like / dislike
  getMyFeedback: (articleId: string) =>
    apiClient.get<MyFeedback>(`/api/v1/intel/articles/${articleId}/feedback`),

  submitFeedback: (articleId: string, data: { feedback: 'like' | 'dislike'; comment?: string }) =>
    apiClient.post<ArticleFeedback>(`/api/v1/intel/articles/${articleId}/feedback`, data),

  deleteFeedback: (articleId: string) =>
    apiClient.delete(`/api/v1/intel/articles/${articleId}/feedback`),

  // AI-generated summary tailored to the org's interest profile
  getPersonalizedSummary: (articleId: string) =>
    apiClient.get<PersonalizedSummary>(`/api/v1/intel/articles/${articleId}/personalized-summary`),

  // Interest type catalogue (for dropdown labels, format hints, validation)
  listInterestTypes: () =>
    apiClient.get<InterestTypeOption[]>('/api/v1/intel/interest-types'),

  // HS code autocomplete — returns distinct codes from org's extracted fields
  hsAutocomplete: (q: string) =>
    apiClient.get<{ results: string[] }>('/api/v1/intel/hs-codes/autocomplete', { params: { q } }),

  // Product description → HS code suggestions
  hsFromDescription: (description: string) =>
    apiClient.post<{
      hs_headings: string[];
      hs_chapters: string[];
      rationale: string;
      description: string;
    }>('/api/v1/intel/interests/from-description', { description }),

  // Knowledge graph stats
  knowledgeGraphStats: () =>
    apiClient.get<{ total_relations: number; by_predicate: Record<string, number>; by_subject_type: Record<string, number> }>(
      '/api/v1/intel/knowledge-graph/stats'
    ),

  // Source preferences — per-org enable/disable news sources
  listMySourcePreferences: () =>
    apiClient.get<OrgSourcePreference[]>('/api/v1/intel/sources/my-preferences'),

  updateSourcePreference: (sourceId: string, is_enabled: boolean) =>
    apiClient.patch<OrgSourcePreference>(`/api/v1/intel/sources/${sourceId}/preference`, { is_enabled }),
};
```

### `src/api/flags.ts` — updated
```typescript
export const flagsApi = {
  listByShipment: (shipmentId: string, status?: 'open' | 'resolved') =>
    apiClient.get<Flag[]>(`/api/v1/shipments/${shipmentId}/flags`, {
      params: status ? { status } : {},
    }),

  resolve: (flagId: string, data: { decision: FlagDecision; chosen_value?: string; note?: string }) =>
    apiClient.post<Flag>(`/api/v1/flags/${flagId}/resolve`, data),

  // NEW — deterministic suggestions for resolving a flag
  suggestions: (flagId: string) =>
    apiClient.get<Suggestion[]>(`/api/v1/flags/${flagId}/suggestions`),
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

// NEW
export const FIELD_NAME_LABELS: Record<FieldName, string> = {
  party_shipper: 'Shipper',
  party_consignee: 'Consignee',
  invoice_value: 'Invoice Value',
  currency: 'Currency',
  gross_weight: 'Gross Weight',
  net_weight: 'Net Weight',
  quantity: 'Quantity',
  hs_code: 'HS Code',
  stated_origin: 'Country of Origin',
  incoterm: 'Incoterm',
  invoice_date: 'Invoice Date',
  shipment_date: 'Issue Date',
  reference: 'Reference Number',
  local_reference: 'Local Reference',
  destination_country: 'Destination Country',
  point_of_entry: 'Point of Entry',
  commodity_description: 'Commodity Description',
};

export const FLAG_TYPE_LABELS: Record<FlagType, string> = {
  missing_document: 'Missing Document',
  missing_field: 'Missing Field',
  mismatch: 'Value Mismatch',
  low_confidence: 'Low Confidence',
  hs_inconsistency: 'HS Code Inconsistency',
};

export const FLAG_SEVERITY_COLORS: Record<FlagSeverity, string> = {
  critical: 'bg-red-100 text-red-700 border-red-200',
  warning: 'bg-amber-100 text-amber-700 border-amber-200',
  info: 'bg-blue-50 text-blue-700 border-blue-200',
};

export const FLAG_SEVERITY_ICON_COLORS: Record<FlagSeverity, string> = {
  critical: 'text-red-500',
  warning: 'text-amber-500',
  info: 'text-blue-400',
};

export const FIELD_STATUS_LABELS: Record<FieldStatus, string> = {
  extracted: 'Extracted',
  confirmed: 'Confirmed',
  corrected: 'Corrected',
};

export const FIELD_STATUS_COLORS: Record<FieldStatus, string> = {
  extracted: 'bg-gray-100 text-gray-600',
  confirmed: 'bg-green-100 text-green-700',
  corrected: 'bg-purple-100 text-purple-700',
};

export const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB

// NEW doc types added in Track A
export const DOC_TYPE_LABELS: Record<DocumentType, string> = {
  // (merge with existing — add these 3)
  mill_certificate: 'Mill Certificate',
  suppliers_declaration: "Supplier's Declaration",
  cmr: 'CMR Consignment Note',
  phytosanitary_certificate: 'Phytosanitary Certificate',
  // ...all previous entries unchanged
};

// NEW
export const INTEL_EVENT_TYPE_LABELS: Record<IntelEventType, string> = {
  tariff_change: 'Tariff Change',
  sanctions: 'Sanctions',
  regulation: 'Regulation Update',
  trade_agreement: 'Trade Agreement',
  market_notice: 'Market Notice',
  other: 'Other',
};

export const INTEL_EVENT_TYPE_COLORS: Record<IntelEventType, string> = {
  tariff_change: 'bg-orange-100 text-orange-700',
  sanctions: 'bg-red-100 text-red-700',
  regulation: 'bg-blue-100 text-blue-700',
  trade_agreement: 'bg-green-100 text-green-700',
  market_notice: 'bg-gray-100 text-gray-700',
  other: 'bg-gray-100 text-gray-600',
};

export const IMPACT_SCORE_COLORS: Record<number, string> = {
  1: 'text-gray-500',
  2: 'text-blue-500',
  3: 'text-yellow-500',
  4: 'text-orange-500',
  5: 'text-red-600',
};

export const INTEREST_TYPE_LABELS: Record<InterestType, string> = {
  hs_chapter: 'HS Chapter',
  hs_heading: 'HS Heading',
  hs_code: 'HS Code',
  country: 'Country',
  party_name: 'Party Name',
  industry: 'Industry',
};

// Format hints shown below the value input in AddInterestDialog
export const INTEREST_TYPE_FORMAT_HINTS: Record<InterestType, string> = {
  hs_chapter: '2-digit number, e.g. 72',
  hs_heading: '4-digit number, e.g. 7208',
  hs_code: '6–10 digit number, e.g. 720851',
  country: '2-letter ISO alpha-2 code, e.g. GB',
  party_name: 'Free text, e.g. Acme Steel Ltd',
  industry: 'Free text, e.g. Automotive',
};
```

---

## 6. Routing

Use `createBrowserRouter` with the following route tree.

| Path | Component | Auth required | Notes |
|---|---|---|---|
| `/login` | `LoginPage` | No | Google Sign-In. Redirect to `/` if already logged in |
| `/register` | `RegisterPage` | No | Google Sign-In + org name/slug form |
| `/onboarding` | `OnboardingPage` | Yes | First-time setup wizard — redirect here after first login |
| `/` | `DashboardPage` | Yes | Default route |
| `/workspace` | `WorkspacePage` | Yes | Unified Email + Documents + Shipments tab view |
| `/workspace/documents/:id` | `DocumentDetailPage` | Yes | Opens from workspace documents tab |
| `/workspace/shipments/:id` | `ShipmentDetailPage` | Yes | Opens from workspace shipments tab |
| `/tradewatch` | `TradeWatchFeedPage` | Yes | TradeWatch intelligence feed |
| `/tradewatch/search` | `TradeWatchSearchPage` | Yes | |
| `/tradewatch/articles/:id` | `TradeWatchArticlePage` | Yes | |
| `/tradewatch/analytics` | `TradeWatchAnalyticsPage` | Yes | |
| `/tradewatch/knowledge-graph` | `TradeWatchKnowledgeGraphPage` | Yes | |
| `/settings/notifications` | `NotificationPrefsPage` | Yes | Per-user notification preferences |
| `/settings/interests` | `InterestsPage` | Yes | Manage interest profile |
| `/settings/sources` | `SourcesPage` | Yes | Manage feed sources (all roles) + admin CRUD |
| `/admin` | `AdminPanelPage` | Yes | Admin and Super Admin — org-scoped panel |
| `/admin/users` | redirects to `/admin?tab=users` | Yes | Admin and Super Admin |
| `/admin/sources` | redirects to `/admin?tab=sources` | Yes | Admin and Super Admin |
| `/admin/jobs` | redirects to `/admin?tab=jobs` | Yes | Admin and Super Admin |
| `/admin/analytics` | redirects to `/admin?tab=analytics` | Yes | Admin and Super Admin |
| `/superadmin` | `SuperAdminPage` | Yes | Super Admin only — cross-org system panel |
| `/superadmin/users` | redirects to `/superadmin?tab=users` | Yes | Super Admin only |
| `/superadmin/orgs` | redirects to `/superadmin?tab=orgs` | Yes | Super Admin only |
| `/superadmin/sources` | redirects to `/superadmin?tab=sources` | Yes | Super Admin only |
| `/superadmin/jobs` | redirects to `/superadmin?tab=jobs` | Yes | Super Admin only |
| `/superadmin/analytics` | redirects to `/superadmin?tab=analytics` | Yes | Super Admin only |

**First-login detection**: after a successful `POST /auth/google` or `POST /auth/register-with-google`, check if the returned user has `onboarding_complete: false`. If so, redirect to `/onboarding` instead of `/`.

Wrap all authenticated routes in an `AuthGuard` component that reads `localStorage.access_token` and redirects to `/login` if missing.

---

## 7. Layout

### AppShell

All authenticated pages render inside `AppShell`:
- Fixed left `Sidebar` (240px wide)
- Scrollable `main` content area
- No top bar — user controls live in the sidebar bottom

### Sidebar navigation items

| Icon | Label | Route | Visible to |
|---|---|---|---|
| LayoutDashboard | Dashboard | `/` | All roles |
| Briefcase | Workspace | `/workspace` | All roles — unified Email/Docs/Shipments |
| Newspaper | TradeWatch | `/tradewatch` | All roles |
| BarChart2 | Analytics | `/tradewatch/analytics` | All roles |
| ShieldCheck | Admin | `/admin` | Admin and Super Admin — org panel |
| ShieldAlert | Super Admin | `/superadmin` | Super Admin only — cross-org system panel |

Active route highlights with a filled background. Sidebar shows the org name at the top.

**Profile menu (bottom-left of sidebar)**:

A circular avatar button at the very bottom of the sidebar shows the user's first initial. Clicking it opens a popover with:

```
┌─────────────────────────────┐
│  ● John Smith               │
│    john@example.com         │
│    Admin                    │
├─────────────────────────────┤
│  🔔 Notification Preferences│  → /settings/notifications
│  ❤️  My Interests            │  → /settings/interests
│  📰 News Sources            │  → /settings/sources
├─────────────────────────────┤
│  🚪 Sign out                │
└─────────────────────────────┘
```

All settings items that were previously scattered as separate sidebar entries are consolidated here.

---

## 8. Pages & Components

### 8.1 Login Page (`/login`)

**Layout**: Centered card. App logo above. Single call-to-action.

```
┌──────────────────────────────────┐
│          BrokerAI                │
│                                  │
│  [G]  Sign in with Google        │
│                                  │
│  Don't have an organisation?     │
│  Set one up →  /register         │
└──────────────────────────────────┘
```

**Flow**:
1. Render `<GoogleLogin>` from `@react-oauth/google`
2. On success → `googleLogin(response.credential)` → `POST /api/v1/auth/google`
3. Store `access_token` in `localStorage`
4. Check if user is first-time (`onboarding_complete: false`) → navigate to `/onboarding`, otherwise → `/`
5. On API 401 ("No account found…"): show error banner: *"No BrokerAI account linked to this Google address. Ask your admin to invite you."*

**Redirect**: if `localStorage.access_token` already exists on page load, redirect to `/` immediately.

---

### 8.2 Register Page (`/register`)

Used only when setting up a **new organisation**. Existing users go to `/login`.

**Step 1** — Google sign-in:
- Render `<GoogleLogin>` button
- On success: capture `credential`, auto-fill email from the decoded token (display only, not editable)

**Step 2** — Organisation details (shown after successful Google sign-in):
- **Organisation name** — text input
- **Organisation slug** — auto-generated from name (lowercase, hyphens), user-editable
- "Create Organisation" button → `POST /api/v1/auth/register-with-google` with `{ credential, org_name, org_slug }`
- On 409 "slug taken": show error under slug field
- On 409 "email exists": show "An account with this Google email already exists — try signing in"
- On success: store `access_token` (issue a follow-up `POST /api/v1/auth/google` with the same credential) → navigate to `/`

**Link**: "Already have an account? Sign in" → `/login`

---

### 8.5 Dashboard Page (`/`)

Calls `GET /api/v1/workspace/dashboard`. Auto-refreshes every 30 seconds via `refetchInterval`.

Layout: 4 stat cards in a 2×2 grid (desktop), then two panels below.

#### Stat Cards

Layout: 2×3 grid on desktop (6 cards total).

| Stat | Field | Icon | Alert color |
|---|---|---|---|
| Total Shipments | `total_shipments` | Ship | — |
| Imported Today | `documents_imported_today` | FileInput | — |
| Needs Classification | `unclassified_documents` | Tag | amber if > 0 |
| Needs Review | `shipments_requiring_review` | AlertCircle | amber if > 0 |
| Critical Issues | `open_flags_critical` | AlertOctagon | red if > 0 — NEW |
| Fields to Review | `pending_field_reviews` | ScanSearch | amber if > 0 — NEW |

Show a number and a small label.

#### Attention Queue — NEW

Source: `attention_queue` from `DashboardStats` (up to 5 shipments with most open critical flags).

Rendered as a compact list below the stat cards:

```
⚠ Shipments needing attention
┌──────────────────────────────────────┐
│ ABCD1234   3 critical issues   [View] │
│ EF567890   1 critical issue    [View] │
└──────────────────────────────────────┘
```

Each row: short shipment ID + flag count + "View" link → `/shipments/:id`.
Hidden entirely when `attention_queue` is empty.

#### Recent Email Imports Panel

Table/list with columns: Subject, Sender, Provider badge, Received date, Attachments count.  
Empty state: "No email imports yet. Connect a mailbox in Email settings."  
Source: `recent_email_imports` from `DashboardStats`.

#### Quick Actions Panel

Buttons:
- "Upload Document" → opens upload dialog (same as document list page upload)
- "View Workspace" → navigates to `/workspace`

---

### 8.NEW Onboarding Wizard (`/onboarding`)

Shown only on first login (`onboarding_complete: false`). A multi-step full-screen wizard. After the final step, call `PATCH /api/v1/workspace/settings` with `{ onboarding_complete: true }` and redirect to `/`.

**Step indicator** at the top: 4 numbered circles connected by a line.

---

**Step 1 — Org Settings**

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1 of 4 · Organisation Settings                        │
│                                                             │
│  Company name     [________________________]                 │
│  Industry sector  [________________________]                 │
│  Primary country  [________________________]                 │
│                                                             │
│  Tolerance thresholds (invoice value mismatch)              │
│  ○ Strict (0%)  ● Moderate (5%)  ○ Relaxed (10%)           │
│                                                             │
│  Document organisation                                      │
│  ○ By shipment  ● By date  ○ By document type              │
│                                                             │
│                               [Skip]  [Next →]             │
└─────────────────────────────────────────────────────────────┘
```

Call `GET /api/v1/workspace/settings` to pre-fill. On Next → `PATCH /api/v1/workspace/settings`.

---

**Step 2 — My Interests**

```
┌─────────────────────────────────────────────────────────────┐
│  Step 2 of 4 · What do you trade?                           │
│                                                             │
│  Describe a product to get HS code suggestions:            │
│  [stainless steel flat-rolled products     ] [Suggest →]   │
│                                                             │
│  Suggested:  [HS 7219 ✓]  [HS 7220 ✓]  [Chapter 72 ✓]    │
│  (Rationale: flat-rolled stainless steel)                   │
│                                                             │
│  Countries  [GB ×] [ES ×]  [+ Select countries ▼]         │
│  (multi-select dropdown, shows flag + name)                 │
│                                                             │
│  Party names  [CHEFFINS ×]  [+ Add]                        │
│  Industries   [Agriculture ×]  [+ Add]                     │
│                                                             │
│  HS Codes — type 2+ digits for autocomplete:               │
│  [87____]  suggestions appear as you type                   │
│                                                             │
│                          [← Back]  [Skip]  [Next →]        │
└─────────────────────────────────────────────────────────────┘
```

- **Product description → HS**: `POST /api/v1/intel/interests/from-description` → show returned `hs_headings` and `hs_chapters` as checkboxes; checked items are added via `POST /api/v1/intel/interests` on Next.
- **Country multi-select**: a searchable dropdown (or `<select multiple>`) listing all ISO countries; selections shown as chips with flag + code. Do NOT require pressing + per country.
- **HS autocomplete**: on typing 2+ digits, call `GET /api/v1/intel/hs-codes/autocomplete?q={prefix}` and show results as a dropdown.
- Party name / Industry: text-only inputs; reject if value contains digits (show inline error).

---

**Step 3 — News Sources**

```
┌─────────────────────────────────────────────────────────────┐
│  Step 3 of 4 · Choose your news sources                     │
│                                                             │
│  TARIFF                                                     │
│  ✓ GOV.UK Trade Tariffs                                    │
│  ✓ HMRC Notices                                            │
│                                                             │
│  SANCTIONS                                                  │
│  ✓ UK Sanctions (OFSI)                                     │
│  ✓ EU Sanctions                                            │
│                                                             │
│  TRADE NEWS                                                 │
│  ✓ BIFA News                                               │
│  □ WCO Committee                                           │
│                                                             │
│                          [← Back]  [Skip]  [Next →]        │
└─────────────────────────────────────────────────────────────┘
```

Load sources from `GET /api/v1/intel/sources/my-preferences`. Toggle each with `PATCH /api/v1/intel/sources/{id}/preference`.

---

**Step 4 — Notification Preferences**

```
┌─────────────────────────────────────────────────────────────┐
│  Step 4 of 4 · How do you want to be alerted?               │
│                                                             │
│  Email me when impact is ≥ ____                            │
│  [● 1-Low  ○ 2-Minor  ● 3-Moderate  ○ 4-High  ○ 5-Critical]│
│                                                             │
│  Impact score guide:                                        │
│  1 · Low      — Background context, no urgent action       │
│  2 · Minor    — Worth monitoring, low trade impact         │
│  3 · Moderate — May affect costs or compliance             │
│  4 · High     — Likely affects your shipments directly     │
│  5 · Critical — Immediate action required (sanctions etc.) │
│                                                             │
│  Event types to receive alerts for:                        │
│  ☑ Tariff changes   ☑ Sanctions   ☑ Regulations          │
│  ☑ Trade agreements  □ General trade news                  │
│                                                             │
│  ✉ Email alerts  [toggle on]                              │
│                                                             │
│                          [← Back]  [Finish ✓]              │
└─────────────────────────────────────────────────────────────┘
```

Save → `PATCH /api/v1/intel/notifications/preferences` + mark onboarding complete.

---

### 8.NEW Workspace Page (`/workspace`)

**Unified view** for Email, Documents, and Shipments — three tabs in one page.

```
┌──────────────────────────────────────────────────────────────┐
│  Workspace                              [Upload Document ↑]  │
│  [📧 Email]  [📄 Documents]  [🚢 Shipments]                  │
└──────────────────────────────────────────────────────────────┘
```

**Email tab** — same content as current `/email` page (EmailConnectionsPage). Calls `GET /api/v1/emails/connections` and `GET /api/v1/emails/imports`.

**Documents tab** — same content as current `/documents` list (DocumentListPage):
- Upload zone + document table with status, type, shipment association
- Click document row → opens `/workspace/documents/:id` (full DocumentDetailPage)
- Includes filter by status, type, shipment

**Shipments tab** — same content as current `/shipments` list (ShipmentListPage):
- Shipment table with reference, status, document count, flag count
- Click row → opens `/workspace/shipments/:id` (full ShipmentDetailPage)

**URL persistence**: use `?tab=email|documents|shipments` query param so the browser back button restores the tab.

**Cross-tab links**: from a shipment, "View documents" opens the Documents tab filtered by `shipment_id`. From a document, "Open shipment" navigates to the Shipments tab for that shipment.

---

### 8.6 Document List Page (`/documents`)

**Header**: "Documents" title + "Upload Document" button (top right)

**Upload flow**:
- Clicking "Upload Document" opens a `Dialog` containing a drag-and-drop zone
- Also shows a file input button as fallback
- **Max file size: 1 GB** per file (enforce client-side with a clear error message)
- **Max files per batch: 15** (multiple files can be selected at once)
- **Accepted types**: PDF, JPEG/PNG (images), Excel (.xls/.xlsx), Word (.docx), CSV, XML
  - `accept` attribute: `".pdf,.jpg,.jpeg,.png,.xls,.xlsx,.docx,.csv,.xml"`
- Single file → call `POST /api/v1/documents/upload` with `FormData`
- Multiple files → call `POST /api/v1/documents/upload/batch` with `FormData` (field name: `files`)
- Show upload progress with a spinner and filename list
- On success: close dialog, invalidate document list query, show toast "N document(s) uploaded — processing started"
- On 409 conflict: show warning "This file has already been uploaded" with a link to the existing document
- On 415 error: show "Unsupported file type" with the list of allowed types

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

**Empty state**: Upload icon + "No documents yet. Upload your first document."

---

### 8.7 Document Detail Page (`/documents/:id`)

Calls `GET /api/v1/documents/:id`, `GET /api/v1/classifications/:id`, and `GET /api/v1/documents/:id/fields` in parallel.

**Layout**: Two columns on desktop (document info left, actions right), with field extraction panel below.

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

**Document Processing Stepper**

Visual stepper showing pipeline state:
```
Uploaded → OCR Pending → OCR Processing → Classified / Needs Review → Matched / Unmatched
```
Active step highlighted. If `ocr_failed`, show red error state on OCR step.

**Extracted Fields Panel** — NEW

Source: `GET /api/v1/documents/:id/fields`

Show below the main panels as a collapsible section "Extracted Fields".

- If no fields yet (extraction pending): show spinner with "Extraction in progress…"
- If fields exist: show as a table/list

Columns:
| Column | Notes |
|---|---|
| Field | `FIELD_NAME_LABELS[field_name]` |
| Value | `value_normalized ?? value_raw` |
| Page | Page number or "—" |
| Confidence | `ConfidenceBadge` (progress bar) |
| Status | `FIELD_STATUS_COLORS` badge (Extracted / Confirmed / Corrected) |
| Actions | "Confirm" button (if status=extracted) + "Correct" button (always) |

**Confirm**: calls `POST /api/v1/fields/:id/confirm` → optimistic update status to `confirmed`, show toast "Field confirmed"

**Correct Field Dialog**: opened by "Correct" button
- Field name label (read-only)
- Current value (read-only, shown for reference)
- "Corrected value" text input (required)
- Submit → `POST /api/v1/fields/:id/correct` with `{ corrected_value }`
- On success: invalidate fields query, toast "Field corrected", close dialog

**Duplicates section** (below fields panel)
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
| Open Flags | Count of open flags — show red badge if > 0, gray "0" otherwise. Tooltip "X open issues" |
| Created | Relative date |
| Updated | Relative date |

Clicking a row navigates to `/shipments/:id`.

**Empty state**: "No shipments yet. Upload documents to start matching."

---

### 8.9 Shipment Detail Page (`/shipments/:id`) — UPDATED

Calls in parallel:
- `GET /api/v1/workspace/shipments/:id`
- `GET /api/v1/workspace/shipments/:id/activity`
- `GET /api/v1/shipments/:id/flags` (all flags, no status filter)
- `GET /api/v1/shipments/:id/fields` (all extracted fields for this shipment)

**Header**
- "Shipment" + short ID (first 8 chars of UUID)
- Status badge (large)
- Status update control: `Select` dropdown (Active / Complete / On Hold) → calls `PATCH /api/v1/shipments/:id` on change with confirm dialog
- **Open flags summary**: if any open flags exist, show a red/amber banner: "X open issue(s) — review required" with a scroll-to-flags link

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

---

#### Flags Panel — NEW

Source: `GET /api/v1/shipments/:id/flags`

**Section header**: "Issues & Mismatches" + open count badge  
**Filter tabs**: All | Open | Resolved

Flags are ordered: critical → warning → info (backend returns them in this order).

Each flag renders as a `FlagCard`:

```
┌─────────────────────────────────────────────────────┐
│ [severity icon] CRITICAL   Value Mismatch           │
│ HS Code differs between documents                   │
│                                                     │
│ Conflicting values:                                 │
│   • Invoice (page 2): 7208.51.00                    │
│   • Packing List (page 1): 7208.52.00               │
│                                                     │
│ [Resolve]                          [open since 2h]  │
└─────────────────────────────────────────────────────┘
```

- Severity icon: `AlertOctagon` (critical/red), `AlertTriangle` (warning/amber), `Info` (info/blue)
- `conflicting_values` list: shows document filename (link to `/documents/:id`) + page number + value
- Resolved flags show a green "Resolved" badge + resolution decision/note
- "Resolve" button (only on open flags) → opens `ResolveFlagDialog`

**Resolve Flag Dialog**:
- Flag title + description shown (read-only)
- Conflicting values list (read-only)
- **Suggestions section** (NEW): call `GET /api/v1/flags/:id/suggestions` on dialog open. If suggestions exist, show each as a clickable chip:
  ```
  💡 Suggested: 7208.51.00  (from Commercial Invoice — Primary source for HS code)
  ```
  Clicking a suggestion pre-fills the `chosen_value` input and sets decision to "Override with value".
- `decision` select: "Accept as-is", "Override with value", "Dismiss"
- `chosen_value` text input (shown only when decision = "Override with value")
- `note` textarea (optional, for all decisions)
- Submit → `POST /api/v1/flags/:id/resolve`
- On success: invalidate flags query + shipment status, toast "Flag resolved", close dialog

**Empty state** (no flags): Green checkmark + "No issues detected. All extracted fields are consistent."

---

#### Extracted Fields Panel — NEW

Source: `GET /api/v1/shipments/:id/fields`

**Section header**: "Extracted Fields" + field count badge

**Group by `field_name`**: each field name has potentially multiple values (one per document). Show grouped rows.

Layout: one row per unique `field_name`.

| Column | Notes |
|---|---|
| Field | `FIELD_NAME_LABELS[field_name]` |
| Values | If all docs agree: single value. If mismatch: show each source doc as a chip with value |
| Confidence | Lowest confidence across sources (worst-case) |
| Status | If any field in group is `extracted` → "Needs Review". If all `confirmed`/`corrected` → "Reviewed" |
| Actions | "Review all" → expands to show per-document breakdown with confirm/correct per field |

**Expand row** shows individual `ExtractedField` records for that field name, each with:
- Source document filename (link)
- `value_normalized ?? value_raw`
- Confidence badge
- Status badge
- "Confirm" + "Correct" buttons (same behavior as Document Detail)

**Empty state**: Spinner if documents are still being processed. "No fields extracted yet — fields are extracted automatically after classification."

**Field name labels** (`FIELD_NAME_LABELS` constant):

| field_name | Display label |
|---|---|
| `party_shipper` | Seller / Consignor |
| `vat_number_seller` | Seller VAT / EIK |
| `rex_number_seller` | Seller REX Number |
| `party_consignee` | Buyer / Consignee |
| `vat_number_buyer` | Buyer VAT Number |
| `rex_number_buyer` | Buyer REX Number |
| `eori_number` | EORI Number |
| `invoice_value` | Invoice Value |
| `vat_value` | VAT Amount |
| `freight_value` | Freight Value |
| `insurance_value` | Insurance Value |
| `currency` | Currency |
| `gross_weight` | Gross Weight |
| `net_weight` | Net Weight |
| `quantity` | Quantity |
| `total_packages` | Total Packages |
| `hs_code` | HS / Commodity Code |
| `commodity_description` | Product Description |
| `lot_number` | Lot Number |
| `product_registration_number` | Product Reg. No. |
| `product_serial_number` | Serial Number |
| `stated_origin` | Country of Origin |
| `destination_country` | Destination Country |
| `place_of_loading` | Place of Loading |
| `incoterm` | Incoterm |
| `preferential_duty` | Preferential Duty |
| `invoice_date` | Invoice Date |
| `due_date` | Payment Due Date |
| `shipment_date` | Shipment Date |
| `expiry_date` | Expiry Date |
| `reference` | Reference / Invoice No. |
| `local_reference` | Local Reference |
| `point_of_entry` | Point of Entry |

**Special display rules:**
- `preferential_duty`: show as a highlighted info box with the full statement text, not just a value chip. Flag with a "Preferential" badge on the document card.
- `eori_number`, `vat_number_*`, `rex_number_*`: show as monospace pill.
- `currency`: when displaying financial values, always append the resolved currency next to amounts.

---

#### Field Mismatch Panel — NEW

Source: `GET /api/v1/shipments/:id/field-mismatches`

This endpoint performs a real-time cross-document comparison for the shipment and returns fields where different documents report conflicting values. It is **separate from the Flags system** — it is a lightweight computed diff, not stored flags.

**Response shape**:
```typescript
interface MismatchValue {
  document_id: string;
  value_raw: string;
  value_normalized: string | null;
  confidence: number;
}

interface FieldMismatch {
  field_name: string;           // e.g. "gross_weight"
  severity: 'error' | 'warning';
  values: MismatchValue[];      // one entry per document that has this field
}

interface ShipmentMismatchOut {
  shipment_id: string;
  mismatches: FieldMismatch[];
}
```

**Fields checked** (in priority order):
| field_name | severity |
|---|---|
| `gross_weight` | error |
| `net_weight` | error |
| `currency` | error |
| `hs_code` | error |
| `invoice_value` | error |
| `stated_origin` | error |
| `destination_country` | warning |
| `incoterm` | warning |
| `party_shipper` | warning |
| `party_consignee` | warning |

**Comparison rules (backend):**
- Decimal fields (`gross_weight`, `net_weight`, `invoice_value`): compare as numbers after stripping units/symbols. Exact Decimal equality required.
- ISO code fields (`currency`, `stated_origin`, `destination_country`, `incoterm`, `hs_code`): case-insensitive exact match.
- String fields (`party_shipper`, `party_consignee`): case-insensitive, whitespace-stripped comparison.

**UI placement**: Show inline in the Extracted Fields Panel as a collapsible "Mismatches" row above the field table if `mismatches.length > 0`.

**Mismatch badge**: In the Shipment Detail tab bar, show a red dot / count badge on the "Fields" tab if there are any `error`-severity mismatches.

**API function** (`src/api/fields.ts`):
```typescript
getShipmentMismatches: (shipmentId: string) =>
  api.get(`/shipments/${shipmentId}/field-mismatches`).then(r => r.data as ShipmentMismatchOut),
```

**Query key** (add to `queryKeys`):
```typescript
shipmentMismatches: (id: string) => ['shipmentMismatches', id],
```

**Invalidation**: invalidate `shipmentMismatches` whenever fields are confirmed, corrected, or a new document is uploaded to the shipment.

---

**Universal extraction note** (behaviour change as of this version):
Every uploaded document now attempts extraction of ALL fields from both Commercial Invoice and Packing List schemas, regardless of document type. The LLM only returns fields it actually finds — so a Bill of Lading will not produce invoice_value, but it will produce party_shipper, gross_weight, hs_code, etc. if those appear in the document. This means the extracted fields list on a shipment is richer, and cross-document mismatches are detected earlier.

---

**Activity Log section**
Source: `GET /api/v1/workspace/shipments/:id/activity`

Timeline list, newest first. Each entry:
- Icon per action type (see below)
- Human-readable action description
- Relative timestamp

**Action icons & labels** (updated with new actions):
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
| `field_extracted` | Scan | "Fields extracted from document" |
| `field_confirmed` | CheckCircle | "Field {field_name} confirmed" |
| `field_corrected` | PenLine | "Field {field_name} corrected" |
| `flag_created` | AlertTriangle | "Issue detected: {flag_title}" |
| `flag_resolved` | CheckCheck | "Issue resolved: {flag_title}" |
| `comparison_run` | GitCompare | "Comparison run — {n} issue(s) found" |
| `settings_updated` | Settings | "Org settings updated" |

Use `details` JSON from the activity log entry to fill in template values.

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
- **Subject keywords**: chip list showing active keywords (default: "Commercial Invoice", "Packing list", "Bill of Materials"). Click "Edit Keywords" to open inline edit.
- "Sync Now" button → calls `POST /api/v1/email/connections/:id/sync` → toast "Sync queued"
- "Disconnect" button → confirm dialog → calls `DELETE /api/v1/email/connections/:id` → toast "Disconnected" + refresh list

**Keyword editing**:
- "Edit Keywords" opens a small popover/inline panel with a tag input (user can add/remove keywords)
- Save → `PATCH /api/v1/email/connections/:id/keywords` with `{ keywords: string[] }`
- Pass `{ keywords: null }` to disable filtering (accept all subjects)
- Toast "Keywords updated" on success

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

**Role edit**: Inline `Select` per row (Admin, Manager, Operator). Super Admin users see an additional "Super Admin" option. On change → `PATCH /api/v1/auth/users/:id` with `{ role }`.

**Active toggle**: Switch per row. On toggle → `PATCH /api/v1/auth/users/:id` with `{ is_active }`.

**Invite User Dialog**:
Fields: email, role (default: Operator) — **no password**  
Note below form: *"The invited user will sign in using Google with this email address."*  
Submit → `POST /api/v1/auth/users` with `{ email, role }`  
On success: close dialog, refresh list, toast "User invited — they can now sign in with Google"

---

### 8.12 Org Settings Page (`/settings/org`) — NEW

**Admin only.** Non-admins see a 403 message.

Calls `GET /api/v1/org/settings`.

**Header**: "Organisation Settings"

**Tolerance Settings Card**

Description: *"These thresholds control when mismatches are flagged. Zero-tolerance fields (HS Code, Origin, Currency) are always flagged on any difference."*

Form fields:

| Field | Label | Notes |
|---|---|---|
| `weight_qty_tolerance_pct` | Weight & Quantity Tolerance (%) | Number input, 0.0–100.0, step 0.1. Default 0.5 |
| `value_tolerance_pct` | Invoice Value Tolerance (%) | Number input, 0.0–100.0, step 0.1. Default 1.0 |
| `name_match_threshold` | Party Name Match Threshold (%) | Number input, 0–100, step 1. Display as % (multiply stored value by 100). Default 93 |

Note: `name_match_threshold` is stored as 0.0–1.0 on the backend (e.g. 0.93). Display as percentage (93%). Convert on submit: `value / 100`.

**Orchestration Settings Card** (new section below Tolerance Settings)

| Field | Label | Notes |
|---|---|---|
| `doc_organization_by` | Organise documents by | Select: Shipment / Client / Lane / Date. Default: Shipment |
| `auto_fix_threshold` | Auto-fix confidence threshold | Slider or number input, 50–100%, step 1. Displayed as %. Default 95%. Store as 0.0–1.0 on submit (÷ 100). |
| `email_critical_alerts` | Email me for critical trade events | Toggle switch. When on, emails are sent for articles with `impact_score ≥ 4`. |

Description: *"When auto-fix confidence exceeds the threshold, mismatches are resolved automatically. Set higher to require more certainty before auto-fixing."*

**OCR Language Settings Card**

| Field | Label | Notes |
|---|---|---|
| `ocr_languages` | OCR Languages | Multi-select checkboxes or tag selector. Value stored as comma-separated codes (e.g. `"eng,fra,deu"`). |

Available languages:
| Code | Language |
|---|---|
| `eng` | English (default) |
| `fra` | French |
| `bul` | Bulgarian |
| `nld` | Dutch |
| `deu` | German |
| `ita` | Italian |

Description: *"Select the languages to use when extracting text from scanned documents. Adding more languages increases accuracy for multilingual documents but may slow processing."*

**"Save Settings"** button → `PATCH /api/v1/org/settings`  
On success: toast "Settings saved", invalidate settings query.

**Zero-tolerance notice** (info box below form):
> The following fields are always flagged on any difference, regardless of tolerance settings: **HS Code**, **Country of Origin**, **Currency**, **Incoterm**.

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

### `FlagCard`
```
Props: { flag: Flag, onResolve: (flag: Flag) => void }
```
Card with severity-colored left border. Shows title, description, conflicting values list (each value linking to the source document), severity badge, created time. "Resolve" button (hidden if already resolved).

### `ImpactBadge` — NEW
```
Props: { score: number }   // 1–5
```
Colored dot + number. Colors from `IMPACT_SCORE_COLORS`. Tooltip: score meaning ("1 = Informational", "5 = Immediate action required").

### `IntelEventBadge` — NEW
```
Props: { event_type: IntelEventType }
```
Pill using `INTEL_EVENT_TYPE_COLORS`.

### `InterestChip` — NEW
```
Props: { interest: UserInterest, onDelete?: () => void }
```
Pill showing `INTEREST_TYPE_LABELS[type]`: value. Delete × button if `onDelete` provided.

### `FieldStatusBadge` — NEW
```
Props: { status: FieldStatus }
```
Pill using `FIELD_STATUS_COLORS`. Labels: Extracted / Confirmed / Corrected.

### `SeverityBadge` — NEW
```
Props: { severity: FlagSeverity }
```
Pill using `FLAG_SEVERITY_COLORS`. Labels: Critical / Warning / Info.

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
  documentFields: (docId: string) => ['documentFields', docId],   // NEW
  shipments: ['shipments'],
  shipment: (id: string) => ['shipment', id],
  shipmentDetail: (id: string) => ['shipmentDetail', id],
  shipmentFields: (id: string) => ['shipmentFields', id],          // NEW
  shipmentFlags: (id: string, status?: string) => ['shipmentFlags', id, status], // NEW
  activityLog: (id: string) => ['activityLog', id],
  emailConnections: ['emailConnections'],
  dashboard: ['dashboard'],
  orgSettings: ['orgSettings'],
  // NEW — Trade Intelligence
  intelFeed: (filters?: object) => ['intelFeed', filters],
  intelSearch: (q: string) => ['intelSearch', q],
  intelArticle: (id: string) => ['intelArticle', id],
  shipmentIntel: (shipmentId: string) => ['shipmentIntel', shipmentId],
  intelInterests: ['intelInterests'],
  intelAlerts: ['intelAlerts'],
  intelSources: ['intelSources'],
  flagSuggestions: (flagId: string) => ['flagSuggestions', flagId],
  intelFilterOptions: ['intelFilterOptions'],
  intelInterestTypes: ['intelInterestTypes'],
  articleFeedback: (articleId: string) => ['articleFeedback', articleId],
  personalizedSummary: (articleId: string) => ['personalizedSummary', articleId],
  mySourcePreferences: ['mySourcePreferences'],
  knowledgeGraphStats: ['knowledgeGraphStats'],
  // Admin panel
  adminUsers: ['adminUsers'],
  adminSources: ['adminSources'],
  adminJobs: (filters?: object) => ['adminJobs', filters],
  adminAnalytics: (days: number) => ['adminAnalytics', days],
};
```

### Refetch intervals

- `dashboard`: every 30 seconds (`refetchInterval: 30_000`)
- `document` detail: every 10 seconds when status is `ocr_pending` or `ocr_processing` (use `refetchInterval` conditionally)
- `documentFields`: every 10 seconds when document status is `classified` but fields array is empty (extraction in progress)
- `shipmentFlags`: no polling (manual invalidation after resolve)
- `intelFeed`: every 5 minutes (`refetchInterval: 300_000`) — new articles arrive hourly from sources
- `intelAlerts`: no polling (manual refresh)
- `flagSuggestions`: no polling (fetched once per dialog open)
- `adminJobs`: every 30 seconds when the tab is open (`refetchInterval: 30_000`) — stop when no jobs have `status=running`
- All others: default (no polling)

---

## 11. Auth Flow

**Sign-in with Google (primary path)**:
1. User lands on `/login`, clicks the Google button (`<GoogleLogin>` from `@react-oauth/google`)
2. Google returns a `credential` (ID token string)
3. Frontend calls `POST /api/v1/auth/google` with `{ credential }`
4. Backend verifies the token via Google's tokeninfo API, finds the user by email, returns our JWT
5. Store `access_token` in `localStorage` → navigate to `/`

**Session check on app start**:
- `useCurrentUser` calls `GET /api/v1/auth/me`; on 401 the axios interceptor clears localStorage and redirects to `/login`

**Logout**: clear `localStorage.access_token`, call `queryClient.clear()`, navigate to `/login`

**Register new org**:
1. `/register` page → user clicks Google button → gets `credential`
2. User fills org name + slug → submit `POST /api/v1/auth/register-with-google`
3. On success → immediately call `POST /api/v1/auth/google` with same credential → store JWT → navigate to `/`

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

**Wrap the app root**:
```tsx
// src/main.tsx
import { GoogleOAuthProvider } from '@react-oauth/google';

<GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID}>
  <App />
</GoogleOAuthProvider>
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
Uploaded → OCR Pending → OCR Processing → Classified / Needs Review → Fields Extracted → Matched / Unmatched
```

If `ocr_failed`, show a red error state on the OCR step.  
If fields are extracted but low-confidence flags exist, show a warning indicator on the "Fields Extracted" step.

---

## 15. Implementation Order

Implement in this order to deliver value incrementally:

1. **Project scaffold**: Vite + React + TypeScript + Tailwind + shadcn/ui setup
2. **API client**: `src/api/client.ts` with auth interceptor
3. **Types**: `src/types/index.ts`
4. **Auth pages**: Login (Google button), Register (Google + org form)
5. **AppShell + Sidebar + routing skeleton**
6. **Dashboard page**
7. **Document List + Upload**
8. **Document Detail + Classification Override + Reassociate + Extracted Fields panel**
9. **Shipment List** (with open-flag count column)
10. **Shipment Detail + Flags Panel + Extracted Fields grouped panel + Activity Log**
11. **Email Connections page**
12. **User Management page** (admin only)
13. **Org Settings page** (admin only)
14. **TradeWatch Feed page** — feed, search, article detail
15. **Shipment TradeWatch panel** (on Shipment Detail)
16. **Sources & Notifications** (in settings/onboarding)
17. **Admin Panel** (`/admin`) — Users tab first (role change), then Sources, Jobs, Analytics
17. **Polish**: empty states, loading states, error handling, responsive layout

---

## 16. Key Business Rules (enforce in UI)

- **Authentication is Google-only**. Never render an email+password login form. The only sign-in control is `<GoogleLogin>` from `@react-oauth/google`.
- **No password fields anywhere** — not in login, register, or invite dialogs. Passwords are not stored for any new account.
- **Invited users**: the admin provides only email + role. The user authenticates via Google using that email. If a user's Google account email doesn't match their invited email, they see "No account found" and must ask their admin.
- **`VITE_GOOGLE_CLIENT_ID` must be set** in `.env`. If missing, the Google button will not render — show a config error in development mode.
- Max upload size is **50 MB**. Reject larger files client-side before calling the API.
- On a **409 Conflict** from upload, show "Duplicate file detected" and link to the existing document.
- The **"Override Classification"** button is always visible on Document Detail, even when no classification exists yet.
- Status badge colors must follow the constants defined in Section 5 — do not invent new colors.
- **Admin-only routes** (`/settings/users`, `/settings/org`): check `user.role === 'admin'` after loading `useCurrentUser`. Redirect or show a 403 message for non-admins.
- **Confidence threshold**: visually distinguish ≥ 70% (good), 50–69% (caution), < 50% (poor). Fields with confidence < 70% must show a visual warning.
- Document detail page **polls every 10 seconds** if status is `ocr_pending` or `ocr_processing`, stops polling once status changes.
- Shipment references: render each `ref_type` + `ref_value` pair as a labeled chip — never just raw values.
- **Flag severity order**: always display critical flags before warning, warning before info. Never mix the order.
- **FlagResolution is append-only**: once a flag is resolved it cannot be un-resolved. The UI must not show an "unresolve" option.
- **Field corrections**: after correcting a field, the old `value_raw` is preserved and shown as "original". Never hide the original extraction.
- **Zero-tolerance fields**: HS Code, Country of Origin, Currency, Incoterm. Any mismatch on these produces a `critical` flag regardless of org settings. Make this visible in the UI with a tooltip or note on those field rows.
- `name_match_threshold` is stored as 0.0–1.0. Always display as a percentage (multiply by 100) in the UI.
- **Suggestions are never auto-applied**: only show them as pre-fill options in the resolve dialog. The user must explicitly click and submit.
- **Intel HS codes**: only displayed when `hs_chapters` / `hs_headings` arrays are non-empty. Never infer HS codes from article text in the UI.
- **Interest validation**: validate client-side before submitting. Country must be 2-letter uppercase ISO alpha-2 (e.g. "GB"). HS chapter = 2 digits, HS heading = 4 digits, HS code = 6–10 digits. **Party name and Industry must contain only letters/spaces/hyphens — no digits.** Show inline error; on 422 from API, show `detail` message.
- **Country multi-select**: the country interest picker must allow selecting multiple countries in one action (multi-select dropdown or checkbox list), not require pressing + once per country.
- **`hs_code` vs `hs_heading`**: "7208" is a 4-digit HS heading, NOT a country. If the user picks type=country and types "7208" the UI must reject it with a format error before the API is called.
- **TradeWatch branding**: the feed section is called "TradeWatch" everywhere in the UI — not "Intel", not "Trade Intelligence", not "Intelligence Feed".
- **Admin panel** (`/admin`): guard with `user.role === 'admin'`. Redirect non-admins to `/` with a toast. Show the "Admin" sidebar item only to admins.
- **Role self-change**: an admin must not be able to demote themselves. Disable the role dropdown for the row matching `currentUser.id` in the Users tab.
- **Source deactivation** (admin): sets `is_active: false` — the source still appears in the list but stops being polled. This is a soft-delete, not a hard delete.
- **Job reprocess**: only available for `status=failed` AND `job_type=enrich`. Show a "Reprocess" button on those rows only.
- **Source preferences**: disabling a source hides its articles from the feed for the whole org. The admin source list (`/intel/sources`) still shows all sources; the preferences page is for feed curation only.
- **Article feedback**: submitting feedback does not re-rank the feed. It is for product analytics only. Never show aggregate like/dislike counts to users.
- **`auto_fix_threshold`**: stored as 0.0–1.0, display and accept as percentage (0–100). Clamp to 50–100% in the UI (backend enforces ge=0.5, le=1.0).
- **`in_app` delivery channel**: removed. Never show "In-App" as a notification channel option in any form or settings page.
- **Sanctions flags** (`flag_type=mismatch`, `severity=critical`, title contains "Sanctions"): highlight with a distinct red banner on Shipment Detail. Never dismiss silently.
- **Interest profile**: `is_explicit=false` interests are shown with a dimmed style and a tooltip "Auto-detected from your shipment history". They cannot be deleted — only explicit interests can be removed.
- **Tabular files** (XLS/XLSX/CSV/XML): upload is supported (same upload UI). Show a spreadsheet icon (`Sheet`) instead of `FileText` for these content types.

---

## 16B. Admin Panel (`/admin`) — Admin only

Single-page admin panel with **four tabs**. Non-admins are redirected to `/` with a toast "Access denied". Tab selection is persisted in the URL as `?tab=users|sources|jobs|analytics`.

```
┌─────────────────────────────────────────────────────────────┐
│  Admin Panel                                                │
│  [👥 Users]  [📡 Sources]  [⚙️ Jobs]  [📊 Analytics]       │
└─────────────────────────────────────────────────────────────┘
```

---

### 16B.1 Users Tab

**Header**: "Users" + "Invite User" button

**Table** (calls `GET /api/v1/auth/users`):

| Column | Notes |
|---|---|
| Name / Email | `email` (no display name stored yet) |
| Role | Dropdown in-row: `admin` / `manager` / `operator` — changing fires `PATCH /api/v1/auth/users/:id` with `{ role }` immediately → toast "Role updated" |
| Status | Green "Active" / Gray "Inactive" badge |
| Joined | `created_at` relative date |
| Actions | Toggle active/inactive (eye icon) + revoke access (X icon, sets `is_active: false`) |

**Role change** — inline dropdown per row, no modal needed:
```
│ john@example.com │ [admin    ▼] │ ● Active │ 3 days ago │ [👁] [✕] │
│ jane@example.com │ [operator ▼] │ ● Active │ 1 week ago │ [👁] [✕] │
```
- Changing the dropdown immediately calls `PATCH /api/v1/auth/users/{id}` with `{ role: "admin"|"manager"|"operator" }`
- Admin cannot demote themselves (disable the dropdown for the current user's own row)

**Invite User dialog** (opens on "Invite User" button):
```
Email address  [jane@example.com        ]
Role           [Operator ▼              ]
               [Cancel]  [Send Invite →]
```
→ `POST /api/v1/auth/users` with `{ email, role }` → toast "User invited. They can sign in with Google using this email."

---

### 16B.2 Sources Tab

**Header**: "News Sources" + "Add Source" button

**Summary chips** (above table):
```
[✓ 12 Active]  [⚠ 2 Degraded]  [✕ 1 Dead]  [📰 847 articles / 24h]
```
Data from `GET /api/v1/intel/sources`.

**Table**:

| Column | Display |
|---|---|
| Name | Source name (bold) |
| Type | `rss` / `scraper` / `sanctions_list` badge |
| Category | tariff / sanctions / regulation / trade_news / market_notice coloured badge |
| URL | truncated link (click → opens in new tab) |
| Cadence | "Every {n} min" |
| Last polled | relative date or "Never" |
| Health | `healthy` (green) / `degraded` (amber) / `dead` (red) / `unknown` (gray) badge |
| Articles | `articles_collected` count |
| Active | toggle switch (`is_active`) |
| Actions | ✏️ Edit  •  ▶ Poll now  •  🗑 Deactivate |

**Add / Edit Source dialog**:
```
Name           [________________________]
Type           [RSS ▼]
Category       [Trade News ▼]
URL            [https://...            ]
Poll every     [60] minutes
Priority       [5] (1–10)
Active         [✓]
               [Cancel]  [Save]
```
- Add → `POST /api/v1/intel/sources`
- Edit → `PATCH /api/v1/intel/sources/:id`
- Deactivate → confirm dialog → `DELETE /api/v1/intel/sources/:id` (soft-delete)
- Poll now → `POST /api/v1/intel/sources/:id/poll` → toast "Poll queued for {name}"

**Error tooltip**: hover red "dead"/"degraded" badge to see `last_error` text.

---

### 16B.3 Jobs Tab

**Header**: "Pipeline Jobs"

**Filter bar**:
- Status chips: All / Pending / Running / Done / Failed (filter `?status=`)
- Type chips: All / collect / parse / enrich / notify (filter `?job_type=`)
- "Refresh" button (refetch every 30s automatically while any job is `running`)

Calls `GET /api/v1/intel/jobs?limit=100&status=…&job_type=…`.

**Table**:

| Column | Display |
|---|---|
| Created | relative time (e.g. "2 min ago") |
| Source | source name (link to Sources tab `?tab=sources`) |
| Type | `collect` / `parse` / `enrich` / `notify` badge |
| Status | `pending` (gray) / `running` (blue spinner) / `done` (green) / `failed` (red) badge |
| Articles | `articles_processed` count |
| Duration | `completed_at − started_at` — shown as "4.2s" or "1m 12s" |
| Error | truncated `error_message` (click to expand full text in a tooltip/popover) |
| Actions | **Reprocess** button — only on `status=failed` AND `job_type=enrich` rows → `POST /api/v1/intel/admin/reprocess/:article_id` |

**Empty state**: "No jobs yet. Jobs are created when sources are polled."

---

### 16B.4 Analytics Tab

**Date range selector**: 7 / 30 / 90 / 365 days (shared across all charts below).

**Summary stats row** (top):
```
[📰 1,247 articles]  [⚡ Avg impact 3.2]  [🌍 42 countries]  [🔗 89 matched]
```

**Country Heatmap** (`GET /api/v1/intel/analytics/heatmap?days=N`):
- Horizontal bar chart (country flag + ISO code + article count)
- Ranked by count, max 20 bars
- Clicking a country navigates to `/tradewatch?country=XX`

**By Event Type** (`GET /api/v1/intel/analytics/by-event-type?days=N`):
- Donut chart, coloured by `INTEL_EVENT_TYPE_COLORS`
- Legend below with count labels

**Impact Timeline** (`GET /api/v1/intel/analytics/impact-timeline?days=N`):
- Line chart: x = date, y = `avg_impact_score` (1–5)
- Secondary bars: `article_count` per day

**Trending Topics** (`GET /api/v1/intel/analytics/trending?limit=20`):
- Tag cloud or ranked table
- Filter chips: hs_chapter / country / event_type / commodity
- Each tag links to `/tradewatch?q={topic_value}`

---

## 17. TradeWatch Pages

### 17.1 TradeWatch Feed Page (`/tradewatch`)

Calls `GET /api/v1/intel/feed` with `refetchInterval: 300_000`.

**Header**: "TradeWatch" title (not "Intel" or "Trade Intelligence") + search input (navigates to `/tradewatch/search?q=...`)

**Filter bar**: load options from `GET /api/v1/intel/filter-options` (`queryKeys.intelFilterOptions`).

- **Event type** — All + options from `filter_options.event_types` (use `label` as display, `value` as param)
- **Country** — "All countries" + sorted list from `filter_options.countries`; validated ISO alpha-2 only
- **Industry** — "All industries" + list from `filter_options.industries`
- **Min impact** — All | ≥3 | ≥4 | ≥5 (use `filter_options.impact_scale` labels for tooltips)
- **Matched only** — Toggle: "My shipments only" (sends `matched_only=true`)

Pass active filters to `intelApi.feed(params)`.

**Feed layout**: card list, newest matched articles first.

Each **IntelArticleCard**:
```
┌──────────────────────────────────────────────────────────────┐
│ [event badge] SANCTIONS   [impact badge] ●●●●● 5            │
│                                                               │
│ Acme Steel Ltd designated under UK sanctions                  │
│ Published: 2 hours ago · Source: UK Sanctions (OFSI)         │
│                                                               │
│ Summary: Acme Steel Ltd has been added to the UK             │
│ consolidated sanctions list following...                      │
│                                                               │
│ 🇬🇧 🇹🇷  HS: 7208  7209                                        │
│                                                               │
│ Matched to your shipments: ABCD1234, EF567890                │
│ match_reason: "party name ∩ sanctions list"                  │
│                                                              │
│ [Read more →]                                                 │
└──────────────────────────────────────────────────────────────┘
```

Fields to show per card:
- `IntelEventBadge` for `event_type`
- `ImpactBadge` for `impact_score`
- Article `title` (clickable → `/intel/articles/:id`)
- Published date (relative) + source name
- `enrichment.summary` (truncated at 150 chars with "…")
- Country flag emojis for `enrichment.countries`
- HS chapter/heading chips for `enrichment.hs_chapters` / `hs_headings`
- If `matches` non-empty: "Matched to your shipments: {short ids}" (each links to `/shipments/:id`)
- `match_reason` shown as a small gray label

**Unmatched articles**: show below matched, with a visual separator "Other trade news". These have empty `matches`.

**Empty state**: Newspaper icon + "No trade intelligence available. Sources are polled hourly."

---

### 17.2 Intel Search Page (`/intel/search`)

Reads `?q=` from query string, pre-fills search input.

Calls `GET /api/v1/intel/search?q={q}` on mount and on input change (debounce 400ms).

**Layout**: search input (large, full-width) + results list using the same `IntelArticleCard` as feed.

**Empty state** (no results): "No articles found for '{q}'."

**Empty state** (no query): Prompt "Enter a search term — e.g. 'steel tariff', 'UK sanctions', 'HS 7208'"

---

### 17.3 Intel Article Page (`/intel/articles/:id`)

Calls `GET /api/v1/intel/articles/:id`.

**Layout**: single column.

**Header section**:
- `IntelEventBadge` + `ImpactBadge`
- Article title (large)
- Published date + source name + source URL (external link)

**Enrichment section** (if enrichment exists):
- Summary (full text, not truncated)
- Countries: flag emoji + ISO code for each
- HS Chapters / Headings: each as a chip → clicking navigates to intel search for that code
- Regulation refs: list
- Impact rationale (italic text)

**Matched shipments section** (if matches non-empty):
- "This article matches {n} of your shipments"
- List: short shipment ID + match_reason + link to `/shipments/:id`

**Full content section**:
- Collapsible "View full source text" → shows `content_raw` in a scrollable pre/code block

---

### 17.4 Intel Alerts Page (`/intel/alerts`)

Calls `GET /api/v1/intel/alerts`.

**Header**: "Alerts" title

**Alert list** — each row:
- Delivery type badge (Email / In-App)
- Subject
- Status badge: green "Sent" / red "Failed"
- Delivered at (relative date)
- "View article" link → `/intel/articles/:article_id` (if `article_id` non-null)

**Empty state**: Bell icon + "No alerts yet. Alerts are sent when high-impact trade events match your shipments."

---

### 17.5 Sources Page (`/settings/sources`) — All roles (admin sees more)

Merges the old "Intel Sources" (admin) and "Source Preferences" (all roles) into a single page. Accessible from the profile menu.

**All roles** see:

**Header**: "News Sources — Choose which sources appear in your feed"

Sources are grouped by category (Tariff / Sanctions / Regulation / Trade News). Each row:

```
┌──────────────────────────────────────────────────────────────┐
│  ● GOV.UK Trade Tariffs   [tariff]   healthy   [enabled  ▼] │
│  ● UK Sanctions (OFSI)    [sanction] healthy   [enabled  ▼] │
│  ○ WCO Committee          [trade]    unknown   [disabled ▼] │
└──────────────────────────────────────────────────────────────┘
```

- Toggle (`is_enabled`) → `PATCH /api/v1/intel/sources/{id}/preference` → invalidate feed + preferences
- Disabled sources are dimmed
- Data: `GET /api/v1/intel/sources/my-preferences`

**Admin-only section** (shown below, or in a separate "Admin" tab):

Full CRUD table with extended columns:
| Column | Notes |
|---|---|
| Name | Source name |
| Type | `rss` / `scraper` / `sanctions_list` badge |
| Category | tariff / sanctions / regulation / trade_news |
| URL | Truncated, external link |
| Cadence | "Every {n} min" |
| Last polled | Relative date or "Never" |
| Health | healthy / degraded / dead / unknown badge |
| Articles | `articles_collected` count |
| Status | Active / Inactive dot |
| Actions | Poll now + Edit + Deactivate |

**Add Source** (admin) → `AddSourceDialog` → `POST /api/v1/intel/sources`
**Edit** → pre-filled dialog → `PATCH /api/v1/intel/sources/:id`
**Deactivate** → confirm → `DELETE /api/v1/intel/sources/:id`
**Poll now** → `POST /api/v1/intel/sources/:id/poll` → toast "Poll queued"

**Error tooltip**: hover the red "Error" badge to see `last_error` text.

**Source Health summary** (admin only, above the table):
- Total active sources / Healthy count / Degraded / Dead
- Articles ingested last 24h

---

### 17.6 Shipment Intel Panel (on Shipment Detail) — NEW

Added to the Shipment Detail Page (`/shipments/:id`) as a new tab/section.

Calls `GET /api/v1/shipments/:id/intel`.

**Section header**: "Related Trade Events" + article count badge

If articles exist: render compact `IntelArticleCard` list (no shipment match line needed since we're already in the shipment context).

If no articles: info box "No trade events matched to this shipment yet. The system checks for matches when new articles are ingested."

---

### 17.7 Interests Management (`/settings/interests`)

Also accessible as Step 2 of the onboarding wizard. Calls `GET /api/v1/intel/interests`.

**Layout**: grouped by `interest_type` in a full-page card.

```
HS Chapters       HS Headings       Countries              Party Names    Industries
[72 ×] [73 ×]    [7208 ×] [+]      [🇬🇧 GB ×] [🇪🇸 ES ×]   [Cheffins ×]   [Agriculture ×]
[+ Add chapter]   [+ Add heading]   [+ Select countries]   [+ Add name]   [+ Add industry]
```

- Each `InterestChip` has delete × (only for `is_explicit=true`)
- Auto-seeded interests (dimmed) show tooltip "Auto-detected from your shipments"

**Adding HS codes — with autocomplete**:
- Text input; on typing 2+ digits call `GET /api/v1/intel/hs-codes/autocomplete?q={prefix}` (debounce 300ms)
- Show results as a dropdown below the input; user selects one → chip added
- Validation: chapter = 2 digits, heading = 4 digits, code = 6–10 digits

**Adding countries — multi-select**:
- Clicking "+ Select countries" opens a searchable dropdown/popover listing all ISO countries (name + flag + code)
- User can **select multiple** in one action; confirm → all selected countries added via `POST /api/v1/intel/interests` in a batch (one request per country, in parallel)
- Never require pressing + once per country

**Adding party name / industry**:
- Text input; client-side reject if value contains any digit (show: "Must contain letters only — no numbers")
- API will also return 422 if validation fails; show `detail` message

**Product description → HS codes**:
- "Describe your product" text area at the top of the HS section
- On submit → `POST /api/v1/intel/interests/from-description` with `{ description }`
- Response shows `hs_headings` + `hs_chapters` as checkboxes with the rationale sentence
- User checks the ones to add, clicks "Add selected" → batch `POST /api/v1/intel/interests`

**Delete**: clicking × → `DELETE /api/v1/intel/interests/:id` → invalidate interests query

---

### 17.8 Intel Analytics Page (`/intel/analytics`)

Three charts with a shared date-range selector (7 / 30 / 90 / 365 days).

**Country Heatmap** — calls `GET /api/v1/intel/analytics/heatmap?days=N`
- World map or, simpler, a horizontal bar chart ranked by `article_count`
- Each bar shows flag + ISO code + count
- Clicking a country filters the feed by that country

**By Event Type** — calls `GET /api/v1/intel/analytics/by-event-type?days=N`
- Donut or bar chart; colour from `INTEL_EVENT_TYPE_COLORS`
- Legend below with count labels

**Impact Timeline** — calls `GET /api/v1/intel/analytics/impact-timeline?days=N`
- Line chart: x = date, y = avg_impact_score (1–5)
- Secondary bars: article_count per day on y2 axis

**Trending Topics** — calls `GET /api/v1/intel/analytics/trending`
- Tag cloud or table; `topic_type` filter chips (hs_chapter / country / event_type / commodity)
- Each topic links to intel search for that term

---

### 17.9 Knowledge Graph Page (`/intel/knowledge-graph`)

An interactive node-link graph (use `react-force-graph` or similar; fallback to a table for simple cases).

**Search panel** (left):
- `subject_type` select: country / hs_code / company / regulation
- `subject_value` text input with autocomplete from `GET /api/v1/intel/tags/autocomplete?prefix=…`
- "Explore" button → `GET /api/v1/intel/knowledge-graph?subject_type=…&subject_value=…`

**Graph canvas** (right):
- Nodes: subject (blue) + related objects (colour by `object_type`)
- Edges labelled with `predicate`
- Clicking a node sets it as the new subject and re-queries
- `confidence` displayed on edge hover

**Table fallback**: if fewer than 10 nodes, render a simple table of (subject → predicate → object) rows with `article_id` link.

---

### 17.10 Notification Preferences (`/settings/notifications`)

Also shown as Step 4 of the onboarding wizard. Calls `GET /api/v1/intel/notifications/preferences` on load.

**Impact score guide** — always displayed on this page (not just in tooltips):

| Score | Level | Meaning |
|---|---|---|
| 1 | Low | Background context, no urgent action needed |
| 2 | Minor | Worth monitoring; low near-term trade impact |
| 3 | Moderate | May affect costs, compliance, or timelines |
| 4 | High | Likely affects your shipments directly — plan ahead |
| 5 | Critical | Immediate action required (e.g. sanctions, port closures) |

**Form**:
- **Min Impact Score** — 5-button toggle (1–5) with the level name and description shown below the selected value. Default: 3 (Moderate).
- **Event Types** — multi-select checkboxes (`tariff_change`, `sanctions`, `regulation`, `trade_agreement`, `trade_news`); empty = all types
- **Email alerts** — single toggle (in_app channel removed)
- **Active** — master toggle; when off, no alerts are sent regardless of other settings

**Note**: The `email_critical_alerts` setting in Org Settings controls org-wide critical-event emails (score = 5). This page controls the per-user threshold and event type filter for personal alerts.

**Save** → `PATCH /api/v1/intel/notifications/preferences` with changed fields only → toast "Preferences saved"

---

### 17.11 Intel Sources Page — Extended (Admin only)

Extends section 17.5 with full CRUD:

**Add Source** button → opens `AddSourceDialog`:
- name, source_type (select), category (select), url, poll_cadence_minutes (number), is_active (toggle), priority (1–10)
- Submit → `POST /api/v1/intel/sources`

**Edit Source** (pencil icon per row) → `AddSourceDialog` pre-filled → `PATCH /api/v1/intel/sources/:id`

**Deactivate** (trash icon) → confirm dialog → `DELETE /api/v1/intel/sources/:id` (soft-delete, sets `is_active=false`)

**Extended table columns** (add to existing):
| Column | Notes |
|---|---|
| Category | tariff / sanctions / regulation / trade_news badge |
| Health | health_status badge: green "healthy" / amber "degraded" / red "dead" / gray "unknown" |
| Articles | `articles_collected` count |
| Priority | small number badge |

---

### 17.12 Intel Jobs Page (`/intel/jobs`) — Admin only

Calls `GET /api/v1/intel/jobs?limit=100`.

**Filter chips**: All / Pending / Running / Done / Failed  
**Filter by type**: all / collect / parse / enrich / notify

**Table**:
| Column | Notes |
|---|---|
| Created | Relative time |
| Source | source_id link to sources page |
| Type | job_type badge |
| Status | colour-coded badge |
| Articles | articles_processed count |
| Duration | completed_at − started_at (human-readable) |
| Error | truncated error_message with expand tooltip |

**Reprocess** button appears on rows with `status=failed` + `job_type=enrich` → `POST /api/v1/intel/admin/reprocess/:article_id`

---

### 17.13 Intel Source Health Dashboard (embedded in 17.11)

Summary row above the sources table:
- Total active sources
- Healthy / Degraded / Dead counts
- Articles ingested last 24h (sum of recent IntelJob `articles_processed`)

Use distinct card chips with coloured borders for quick at-a-glance status.

---

### 17.14 Article Feedback (like / dislike)

Shown on every `IntelArticleCard` in the feed and on the `IntelArticlePage`.

On mount, call `GET /api/v1/intel/articles/:id/feedback` (`queryKeys.articleFeedback(id)`) to hydrate the current state.

**Controls** (below the article summary):
```
[👍 Like]  [👎 Dislike]        ← toggle buttons; selected state is highlighted
```

- Clicking Like or Dislike when none is set → `POST /api/v1/intel/articles/:id/feedback` with `{ feedback: 'like'|'dislike' }`
- Clicking the same button again → `DELETE /api/v1/intel/articles/:id/feedback` (unset)
- Clicking the opposite button → `POST` with new value (upserts server-side)
- Optional comment: clicking the active feedback button opens a small textarea for a comment. Submit updates the same POST endpoint.
- Invalidate `articleFeedback(id)` after each mutation. Show toast only on error.

---

### 17.15 Personalized Summary

On `IntelArticlePage`, show a "Personalized Summary" section after the enrichment section.

- Lazy-load: show a "Get my summary" button. On click, call `GET /api/v1/intel/articles/:id/personalized-summary` (`queryKeys.personalizedSummary(id)`). Cache result (no polling).
- While loading: spinner + "Generating summary tailored to your interests…"
- On success:
  ```
  ✨ Summary for your interests
  [summary text]

  Relevant to: [HS 7208]  [Country: GB]  [Steel industry]   ← chips from relevant_interests
  ```
- If `general_summary` differs from the personalized one, show "General summary" below in collapsed format.
- On error (e.g. no org interests configured): show "Add interests to your profile to get personalized summaries." with a link to the interests panel.

---

### 17.16 Source Preferences Page (`/intel/sources/preferences`)

Accessible from the Feed page via a "Manage Sources" link (non-admin users can access this — it only affects their org's feed, not the global source list).

Calls `GET /api/v1/intel/sources/my-preferences` (`queryKeys.mySourcePreferences`).

**Header**: "News Sources" — "Choose which sources appear in your feed"

**Layout**: grouped by `category` (Tariff / Sanctions / Regulation / Trade News).

Each source row:
```
┌─────────────────────────────────────────────────────────────────┐
│  ● UK Sanctions (OFSI)        [sanctions]         [enabled ▼]   │
│  ● GOV.UK Trade Tariffs       [tariff]            [enabled ▼]   │
│  ● BIFA News                  [trade_news]        [disabled ▼]  │
└─────────────────────────────────────────────────────────────────┘
```

- Toggle switch per source (`is_enabled`)
- On toggle → `PATCH /api/v1/intel/sources/{source_id}/preference` with `{ is_enabled }` → invalidate `mySourcePreferences` + `intelFeed`
- Disabled sources still appear in the list but are visually dimmed and excluded from the feed
- `is_enabled: true` is the implicit default for sources with no preference record

**Add to Sidebar**: add "Sources" as a sub-item under "Trade Intel" (visible to all roles).

**Add to routing table**:

| Path | Component | Auth required | Notes |
|---|---|---|---|
| `/intel/sources/preferences` | `IntelSourcePreferencesPage` | Yes | All roles — manage org feed sources |

---

## 18. Super Admin Panel (`/superadmin`)

Accessible only to users with `role === 'super_admin'`. Any other user who navigates here sees a "403 — Forbidden" page. Guard this route the same way as the admin panel but check `role === 'super_admin'` specifically.

### Layout

Same `AppShell` as all authenticated pages. The sidebar shows a **ShieldAlert** icon for "Super Admin" → `/superadmin` visible only to `super_admin` users.

The page is a tabbed interface with four tabs: **Users · Organisations · Sources · Jobs · Analytics**.

---

### 18.1 Users Tab

**API**: `GET /api/v1/admin/users` (query params: `is_active`, `role`, `org_id`)  
**Query key**: `queryKeys.superAdminUsers(filters)`

**Header**: "All Users" + count badge + search/filter bar

**Filters** (above the table):
- Search by email (client-side filter)
- Role dropdown (super_admin / admin / manager / operator / all)
- Org dropdown (populated from org list)
- Active/Inactive toggle

**Users table** columns:

| Column | Notes |
|---|---|
| Email | |
| Organisation | `org_name` (org_slug in sub-text) |
| Role | Badge with colour: Super Admin (purple), Admin (blue), Manager (teal), Operator (gray) |
| Status | Active / Inactive |
| Joined | Date |
| Actions | Role dropdown + Active toggle |

**Role edit**: Inline `Select` with all four roles (Super Admin / Admin / Manager / Operator). On change → `PATCH /api/v1/admin/users/:id` with `{ role }`. Disable own row's role dropdown (cannot self-demote).

**Active toggle**: `PATCH /api/v1/admin/users/:id` with `{ is_active: false }`. Show confirmation dialog before deactivating.

**Response shape** (`UserOutWithOrg`):
```typescript
interface UserOutWithOrg {
  id: string;
  email: string;
  org_id: string;
  org_name: string;
  org_slug: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}
```

---

### 18.2 Organisations Tab

**API**: `GET /api/v1/admin/organizations`  
**Query key**: `queryKeys.superAdminOrgs`

**Header**: "All Organisations" + "Create Organisation" button

**Table** columns:

| Column | Notes |
|---|---|
| Name | |
| Slug | Monospace |
| Users | `user_count` |
| Created | Date |
| Actions | Edit name/slug button |

**Create Organisation Dialog**:  
Fields: name, slug (auto-slugify from name, editable).  
Submit → `POST /api/v1/admin/organizations` with `{ name, slug }`.

**Edit Organisation Dialog**:  
Pre-filled fields: name, slug.  
Submit → `PATCH /api/v1/admin/organizations/:id` with `{ name?, slug? }`.

**Response shape** (`OrgOutWithStats`):
```typescript
interface OrgOutWithStats {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  user_count: number;
}
```

---

### 18.3 Sources Tab

Same as the existing admin Sources tab but uses the super-admin endpoints which are not org-scoped:

- `GET /api/v1/admin/sources` — list all sources
- `POST /api/v1/admin/sources` — create source
- `PATCH /api/v1/admin/sources/:id` — update source
- `DELETE /api/v1/admin/sources/:id` — deactivate source (soft-delete, sets `is_active: false`)

**Table** columns: Name, URL, Category, Type, Priority, Status (Active/Inactive), Last Polled, Articles, Actions.

**Create Source Dialog**: name, url, category, source_type, poll_cadence_minutes (default 60), priority (1–10, default 5).

**Edit Source Dialog**: same fields, pre-filled.

**Deactivate button**: shows confirmation: "This source will stop being polled. Existing articles are kept."

---

### 18.4 Jobs Tab

**API**: `GET /api/v1/admin/jobs?limit=100&status=&source_id=`  
**Query key**: `queryKeys.superAdminJobs(filters)`  
**Poll interval**: 30 seconds (active jobs change status)

**Filters**: status (all / running / completed / failed), source dropdown.

**Table** columns: Job Type, Source, Status, Articles Processed, Started, Completed, Error (truncated, tooltip for full text).

**Colour-coded status**: running (blue), completed (green), failed (red).

---

### 18.5 Analytics Tab

**API**: `GET /api/v1/admin/analytics`  
**Query key**: `queryKeys.superAdminAnalytics`  
**Cache**: 5 minutes (stale-while-revalidate)

**Layout** — stat cards in a 3-column grid:

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Organisations│  │ Total Users  │  │ Active Users │
│     12       │  │    87        │  │    74        │
└──────────────┘  └──────────────┘  └──────────────┘

┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Sources      │  │ Active Sources│  │ Articles     │
│     24       │  │    20        │  │   14,882     │
└──────────────┘  └──────────────┘  └──────────────┘

┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Enriched     │  │ Total Jobs   │  │ Failed Jobs  │
│   13,200     │  │   1,440      │  │      8       │
└──────────────┘  └──────────────┘  └──────────────┘
```

Below the grid: a **Users by Role** horizontal bar chart (`by_role` breakdown from the API).

---

### 18.6 API functions (`src/api/admin.ts`)

```typescript
export const adminApi = {
  // Users
  listUsers: (filters?: { is_active?: boolean; role?: UserRole; org_id?: string }) =>
    api.get('/admin/users', { params: filters }).then(r => r.data as UserOutWithOrg[]),
  updateUser: (userId: string, data: { role?: UserRole; is_active?: boolean }) =>
    api.patch(`/admin/users/${userId}`, data).then(r => r.data as UserOutWithOrg),
  deactivateUser: (userId: string) =>
    api.delete(`/admin/users/${userId}`),

  // Organisations
  listOrgs: () =>
    api.get('/admin/organizations').then(r => r.data as OrgOutWithStats[]),
  createOrg: (data: { name: string; slug: string }) =>
    api.post('/admin/organizations', data).then(r => r.data as OrgOut),
  updateOrg: (orgId: string, data: { name?: string; slug?: string }) =>
    api.patch(`/admin/organizations/${orgId}`, data).then(r => r.data as OrgOut),

  // Sources
  listSources: () =>
    api.get('/admin/sources').then(r => r.data as IntelSourceOut[]),
  createSource: (data: IntelSourceCreate) =>
    api.post('/admin/sources', data).then(r => r.data as IntelSourceOut),
  updateSource: (sourceId: string, data: Partial<IntelSourceCreate>) =>
    api.patch(`/admin/sources/${sourceId}`, data).then(r => r.data as IntelSourceOut),
  deleteSource: (sourceId: string) =>
    api.delete(`/admin/sources/${sourceId}`),

  // Jobs
  listJobs: (filters?: { status?: string; source_id?: string; limit?: number }) =>
    api.get('/admin/jobs', { params: filters }).then(r => r.data as IntelJobOut[]),

  // Analytics
  analytics: () =>
    api.get('/admin/analytics').then(r => r.data),
};
```

---

### 18.7 Query keys

Add to `queryKeys` in `src/api/queryKeys.ts`:

```typescript
superAdminUsers: (filters?: object) => ['superAdminUsers', filters],
superAdminOrgs: ['superAdminOrgs'],
superAdminSources: ['superAdminSources'],
superAdminJobs: (filters?: object) => ['superAdminJobs', filters],
superAdminAnalytics: ['superAdminAnalytics'],
```

---

### 18.8 Business rules

- Only `super_admin` users can access `/superadmin/*`. Guard client-side and trust the 403 from the server.
- A super admin cannot demote themselves (the API enforces this; disable own role dropdown client-side too).
- A super admin cannot deactivate themselves (disable own active toggle).
- Role badge colours: `super_admin` = purple (`bg-purple-100 text-purple-800`), `admin` = blue, `manager` = teal, `operator` = gray.
- Deactivating a user is a soft delete (`is_active: false`). No hard deletes from the UI.
- All super-admin mutations invalidate the relevant super-admin query key on success.
