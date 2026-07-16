# Document Upload & Extraction — Frontend Spec

> **Purpose**: This document describes everything the frontend needs to rewrite the document upload, processing, and field extraction flow. It supersedes any earlier document-upload or field-extraction sections in `FRONTEND_SPEC.md`.

---

## 0. Migration Guide — What Changed

This section tells the frontend developer exactly **what to update** versus the previous implementation. Each item is marked with the action required.

### 0.1 File Upload — accept more formats

**Before**: upload zone accepted only `PDF`, `JPG`, `PNG`.

**Now**: also accept `WEBP`, `DOCX`, `XLSX`, `XLS`, `CSV`.

**Change required**: update `<input accept="">` and client-side validation (see §10).

---

### 0.2 New `DocumentStatus` values

**Before**: document could be `uploaded → processing → classified → matched / unmatched`.

**Now**: the processing step is split into two statuses:

| Old value | New value | Meaning |
|---|---|---|
| `processing` | `ocr_pending` | queued, not started yet |
| `processing` | `ocr_processing` | actively running |
| *(none)* | `ocr_failed` | extraction failed — show Retry |
| *(none)* | `needs_review` | classified but confidence < 70% |

**Change required**: if you were comparing `status === 'processing'`, replace with `status === 'ocr_pending' || status === 'ocr_processing'`. Add UI states for `ocr_failed` and `needs_review`.

---

### 0.3 Field extraction is now universal (not per-document-type)

**Before**: only the fields relevant to the classified document type were returned. A Packing List returned packing-list fields; a Commercial Invoice returned invoice fields.

**Now**: every document is scanned for **all 31 fields** (see §5). The extractor only returns fields it finds — but it looks for all of them regardless of document type.

**Change required**: no schema change needed — `ExtractedField[]` shape is the same. But your UI must no longer filter or label fields based on document type. Show all returned fields.

---

### 0.4 New endpoint: Document Products  ← **add new tab/panel**

**Before**: no product-line data was stored. Fields were the only extraction output.

**Now**: after extraction, each document has a list of `DocumentProduct` rows — one per line item extracted from the document (e.g. each product on a commercial invoice).

**New endpoints**:
```
GET /api/v1/documents/{document_id}/products   → DocumentProduct[]
GET /api/v1/shipments/{shipment_id}/products   → DocumentProduct[]
```

**Change required**: add a **"Products" tab** to the Document Detail page and a products section to the Shipment Detail page (see §11, §12.2). These did not exist before.

---

### 0.5 New endpoint: Cross-document mismatch detection  ← **add banner**

**Before**: no mismatch detection existed. Users had to compare documents manually.

**Now**: a single on-demand call returns which fields disagree across documents in a shipment, with severity (`error` / `warning`).

**New endpoint**:
```
GET /api/v1/shipments/{shipment_id}/field-mismatches   → ShipmentMismatchOut
```

**Change required**: add a **mismatch banner** at the top of the Shipment Detail Fields tab (see §12.1). Call this endpoint whenever the Fields tab is opened. Show nothing if `mismatches` array is empty.

---

### 0.6 Shipment auto-linking by invoice number  ← **handle new status**

**Before**: documents were linked to shipments manually or by an explicit shipment_id passed at upload time.

**Now**: if the extraction finds an `invoice_number`, the backend automatically finds or creates a shipment and sets `document.shipment_id`. The document status transitions to `matched`.

**Change required**:
- When polling detects `status === 'matched'` AND `shipment_id` is newly set, show a toast: *"Grouped into Shipment — view shipment"* with a link.
- Do not assume `shipment_id` is null after upload; re-read it after polling completes.

---

### 0.7 Fields endpoint: `shipment_id` is now populated on fields

**Before**: `ExtractedField.shipment_id` was typically `null` at extraction time.

**Now**: after auto-linking, existing `ExtractedField` rows on that document are backfilled with the resolved `shipment_id`. Queries to `GET /shipments/{id}/fields` return all fields across all documents in the shipment.

**Change required**: if you were reading fields only at document level, also call `GET /shipments/{id}/fields` on the Shipment Detail page to get the unified field view.

---

### 0.8 Summary checklist for the frontend developer

| # | What to change | Where in this spec |
|---|---|---|
| 1 | Extend upload `accept` to include WEBP/DOCX/XLSX/CSV | §10 |
| 2 | Handle `ocr_pending`, `ocr_processing`, `ocr_failed`, `needs_review` statuses | §2, §10 |
| 3 | Remove document-type-based field filtering | §0.3 |
| 4 | Add Products tab to Document Detail | §11 |
| 5 | Add Products section to Shipment Detail | §12.2 |
| 6 | Add Mismatch banner to Shipment Detail Fields tab | §12.1 |
| 7 | On `status=matched`, show "Grouped into Shipment" toast | §0.6 |
| 8 | On Shipment Detail, fetch `GET /shipments/{id}/fields` for unified view | §12.3 |
| 9 | Add new query keys and invalidation rules | §8, §9 |

---

## 1. Supported File Formats

| Format | Extensions | MIME type |
|--------|-----------|-----------|
| PDF | `.pdf` | `application/pdf` |
| JPEG | `.jpg` `.jpeg` | `image/jpeg` |
| PNG | `.png` | `image/png` |
| WebP | `.webp` | `image/webp` |
| Word | `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| Excel | `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| CSV | `.csv` | `text/csv` |
| Old Excel | `.xls` | `application/vnd.ms-excel` |

Max file size: **1 GB per file**. Max batch: **15 files**.

---

## 2. Document Status Flow

```
UPLOADED
  └─► OCR_PENDING / OCR_PROCESSING
        └─► CLASSIFIED
              └─► MATCHED          (document auto-linked to a shipment)
              └─► UNMATCHED        (no shipment found)
              └─► NEEDS_REVIEW     (classification confidence < 70%)
```

After upload, poll `GET /api/v1/documents/{id}` every 3 seconds until `status` is no longer `uploaded` or `ocr_pending`. Once `classified` or `matched`, the fields and products are ready.

---

## 3. TypeScript Types

```typescript
// ── Document ──────────────────────────────────────────────────────────────────
type DocumentStatus =
  | 'uploaded' | 'ocr_pending' | 'ocr_processing' | 'ocr_failed'
  | 'classified' | 'matched' | 'unmatched' | 'needs_review';

type DocumentSource = 'upload' | 'email';

interface DocumentOut {
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
  updated_at: string;
  download_url?: string;       // only on GET /documents/{id}
}

// ── Extracted Field ───────────────────────────────────────────────────────────
type ExtractedFieldStatus = 'extracted' | 'confirmed' | 'corrected';
type FieldType = 'string' | 'decimal' | 'date' | 'iso_code';

interface ExtractedField {
  id: string;
  document_id: string;
  shipment_id: string | null;
  org_id: string | null;
  field_name: string;          // see Field Name Reference below
  value_raw: string;           // exact text from the document
  value_normalized: string | null; // ISO-formatted / canonical value
  field_type: FieldType | null;
  confidence: number;          // 0.0 – 1.0
  page_number: number | null;
  status: ExtractedFieldStatus;
  confirmed_at: string | null;
  confirmed_by: string | null;
  corrected_value: string | null;
  corrected_by: string | null;
  corrected_at: string | null;
  created_at: string;
}

// ── Document Product ──────────────────────────────────────────────────────────
interface DocumentProduct {
  id: string;
  document_id: string;
  shipment_id: string | null;
  org_id: string;
  product_name: string | null;
  material: string | null;
  intended_use: string | null;
  description: string | null;
  quantity: string | null;          // e.g. "1kg", "450gm", "12 pcs"
  unit_price: string | null;        // numeric string, e.g. "5.20"
  currency: string | null;          // ISO 4217, e.g. "GBP"
  origin_country: string | null;    // ISO 3166-1 alpha-2, e.g. "BG"
  destination_country: string | null;
  existing_hs_code: string | null;  // 6–10 digit commodity code
  missing_required_fields: string[] | null; // ["material", "intended_use"]
  is_ready_to_classify: boolean;
  created_at: string;
}

// ── Mismatch ──────────────────────────────────────────────────────────────────
interface MismatchValue {
  document_id: string;
  value_raw: string;
  value_normalized: string | null;
  confidence: number;
}

interface FieldMismatch {
  field_name: string;
  severity: 'error' | 'warning';
  values: MismatchValue[];    // one per document that has this field
}

interface ShipmentMismatchOut {
  shipment_id: string;
  mismatches: FieldMismatch[];
}
```

---

## 4. API Reference

All endpoints are prefixed with `/api/v1`. Auth: `Authorization: Bearer <token>` header required on every call.

### 4.1 Upload

#### Single upload
```
POST /api/v1/documents/upload
Content-Type: multipart/form-data

Field: file  (binary)
```
**Response**: `201 DocumentOut`

#### Batch upload (up to 15 files)
```
POST /api/v1/documents/upload/batch
Content-Type: multipart/form-data

Field: files[]  (binary, repeated)
```
**Response**: `201 DocumentOut[]`

**Errors**:
- `413` — file exceeds 1 GB
- `415` — unsupported extension
- `400` — batch exceeds 15 files

---

### 4.2 Document Queries

#### Get single document + download URL
```
GET /api/v1/documents/{document_id}
```
**Response**: `200 DocumentOut` (includes `download_url`, 1-hour presigned S3 URL)

#### List documents (optionally scoped to shipment)
```
GET /api/v1/documents/?shipment_id={uuid}
```
**Response**: `200 DocumentOut[]`

#### Delete document
```
DELETE /api/v1/documents/{document_id}
```
**Response**: `204`

---

### 4.3 Extracted Fields

Fields are extracted automatically after a document is classified. Every document type is scanned for all fields below — the extractor only returns what it finds.

#### Fields for one document
```
GET /api/v1/documents/{document_id}/fields
```
**Response**: `200 ExtractedField[]`

#### Fields for a shipment (all documents)
```
GET /api/v1/shipments/{shipment_id}/fields
```
**Response**: `200 ExtractedField[]`

#### Confirm a field (user validates the extracted value)
```
POST /api/v1/fields/{field_id}/confirm
```
**Response**: `200 ExtractedField`

#### Correct a field (user provides a corrected value)
```
POST /api/v1/fields/{field_id}/correct
Body: { "corrected_value": "string" }
```
**Response**: `200 ExtractedField`

---

### 4.4 Document Products

Structured per-product lines extracted by the classification API.

#### Products for one document
```
GET /api/v1/documents/{document_id}/products
```
**Response**: `200 DocumentProduct[]`

#### Products for a shipment (all documents)
```
GET /api/v1/shipments/{shipment_id}/products
```
**Response**: `200 DocumentProduct[]`

---

### 4.5 Cross-Document Mismatch Detection

Compares field values across all documents in a shipment. Computed on-demand — not stored.

```
GET /api/v1/shipments/{shipment_id}/field-mismatches
```
**Response**: `200 ShipmentMismatchOut`

**Severity rules**:
| field_name | severity |
|---|---|
| `gross_weight` | **error** |
| `net_weight` | **error** |
| `currency` | **error** |
| `hs_code` | **error** |
| `invoice_value` | **error** |
| `stated_origin` | **error** |
| `destination_country` | warning |
| `incoterm` | warning |
| `party_shipper` | warning |
| `party_consignee` | warning |

**Comparison rules**:
- Decimal fields: compare numeric values (units stripped). Exact equality.
- ISO codes: case-insensitive exact match.
- String fields: case-insensitive, whitespace-trimmed.

---

## 5. Field Name Reference

All `field_name` values used in `ExtractedField.field_name`:

| field_name | Display label | Type | Notes |
|---|---|---|---|
| `party_shipper` | Seller / Consignor | string | Full name + address |
| `vat_number_seller` | Seller VAT / EIK | string | EU VAT, EIK (Bulgaria), etc. |
| `rex_number_seller` | Seller REX Number | string | e.g. `REX BG123456789` |
| `party_consignee` | Buyer / Consignee | string | Full name + address |
| `vat_number_buyer` | Buyer VAT Number | string | |
| `rex_number_buyer` | Buyer REX Number | string | |
| `eori_number` | EORI Number | string | 2-letter country + up to 15 alphanum |
| `invoice_value` | Invoice Value | decimal | Exclude VAT |
| `vat_value` | VAT Amount | decimal | Tax amount separately |
| `freight_value` | Freight Value | decimal | |
| `insurance_value` | Insurance Value | decimal | |
| `currency` | Currency | iso_code | ISO 4217 |
| `gross_weight` | Gross Weight | decimal | Includes unit in `value_raw` e.g. `830 kg` |
| `net_weight` | Net Weight | decimal | |
| `quantity` | Quantity | decimal | |
| `total_packages` | Total Packages | decimal | |
| `hs_code` | HS / Commodity Code | string | 6–10 digits |
| `commodity_description` | Product Description | string | |
| `lot_number` | Lot Number | string | |
| `product_registration_number` | Product Reg. No. | string | |
| `product_serial_number` | Serial Number | string | |
| `stated_origin` | Country of Origin | iso_code | ISO 3166-1 alpha-2 |
| `destination_country` | Destination Country | iso_code | |
| `place_of_loading` | Place of Loading | string | |
| `incoterm` | Incoterm | iso_code | Incoterms 2020 |
| `preferential_duty` | Preferential Duty | string | Full self-certification statement |
| `invoice_date` | Invoice Date | date | ISO 8601 in `value_normalized` |
| `due_date` | Payment Due Date | date | |
| `shipment_date` | Shipment Date | date | |
| `expiry_date` | Expiry Date | date | |
| `reference` | Reference / Invoice No. | string | May contain multiple refs separated by `;` |
| `local_reference` | Local Reference | string | |
| `point_of_entry` | Point of Entry | string | |

**Display rules**:
- For `decimal` fields: show `value_normalized` (pure number) + append currency / unit where relevant.
- For `date` fields: show `value_normalized` (YYYY-MM-DD) formatted to locale.
- For `iso_code` fields: show flag + code (e.g. 🇬🇧 GBP).
- For `preferential_duty`: render as a highlighted info box with the full statement text.
- For `eori_number`, `vat_number_*`, `rex_number_*`: monospace pill.
- Confidence < 0.70: show amber badge ("Low confidence").
- `status = 'corrected'`: display `corrected_value`, strike through `value_raw`.

---

## 6. Shipment Auto-Linking by Invoice Number

When the classification API returns `shipment.invoice_number`, the backend:
1. Searches for an existing shipment with that invoice reference in the org.
2. If found → links the document to that shipment.
3. If not found → creates a new shipment and records the invoice reference.

**Result**: multiple documents sharing the same `invoice_number` (e.g. a commercial invoice and a packing list) are automatically grouped into one shipment — no manual linking needed.

The document's `shipment_id` is updated after extraction completes. If you poll `GET /documents/{id}` and see a non-null `shipment_id`, the grouping has happened.

---

## 7. API Functions (`src/api/`)

### `src/api/documents.ts`

```typescript
import { api } from './client';
import type { DocumentOut } from '../types';

export const documentsApi = {
  upload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<DocumentOut>('/documents/upload', form).then(r => r.data);
  },

  uploadBatch: (files: File[]) => {
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    return api.post<DocumentOut[]>('/documents/upload/batch', form).then(r => r.data);
  },

  get: (documentId: string) =>
    api.get<DocumentOut>(`/documents/${documentId}`).then(r => r.data),

  list: (shipmentId?: string) =>
    api.get<DocumentOut[]>('/documents/', { params: shipmentId ? { shipment_id: shipmentId } : {} })
       .then(r => r.data),

  delete: (documentId: string) =>
    api.delete(`/documents/${documentId}`),
};
```

### `src/api/fields.ts`

```typescript
import { api } from './client';
import type { ExtractedField, DocumentProduct, ShipmentMismatchOut } from '../types';

export const fieldsApi = {
  // Extracted fields
  getForDocument: (documentId: string) =>
    api.get<ExtractedField[]>(`/documents/${documentId}/fields`).then(r => r.data),

  getForShipment: (shipmentId: string) =>
    api.get<ExtractedField[]>(`/shipments/${shipmentId}/fields`).then(r => r.data),

  confirm: (fieldId: string) =>
    api.post<ExtractedField>(`/fields/${fieldId}/confirm`).then(r => r.data),

  correct: (fieldId: string, correctedValue: string) =>
    api.post<ExtractedField>(`/fields/${fieldId}/correct`, { corrected_value: correctedValue })
       .then(r => r.data),

  // Products
  getProductsForDocument: (documentId: string) =>
    api.get<DocumentProduct[]>(`/documents/${documentId}/products`).then(r => r.data),

  getProductsForShipment: (shipmentId: string) =>
    api.get<DocumentProduct[]>(`/shipments/${shipmentId}/products`).then(r => r.data),

  // Mismatches
  getMismatches: (shipmentId: string) =>
    api.get<ShipmentMismatchOut>(`/shipments/${shipmentId}/field-mismatches`).then(r => r.data),
};
```

---

## 8. Query Keys (`src/api/queryKeys.ts`)

Add or replace:

```typescript
export const queryKeys = {
  // ... existing keys ...

  document: (id: string) => ['document', id] as const,
  documentList: (shipmentId?: string) => ['documents', shipmentId] as const,
  documentFields: (documentId: string) => ['fields', 'document', documentId] as const,
  documentProducts: (documentId: string) => ['products', 'document', documentId] as const,
  shipmentFields: (shipmentId: string) => ['fields', 'shipment', shipmentId] as const,
  shipmentProducts: (shipmentId: string) => ['products', 'shipment', shipmentId] as const,
  shipmentMismatches: (shipmentId: string) => ['mismatches', shipmentId] as const,
};
```

---

## 9. Query Invalidation Rules

| Event | Invalidate |
|---|---|
| Document uploaded | `documentList` |
| Document polled → status changed | `document(id)`, `shipmentFields(shipmentId)`, `shipmentProducts(shipmentId)`, `shipmentMismatches(shipmentId)` |
| Field confirmed | `documentFields(documentId)`, `shipmentFields(shipmentId)`, `shipmentMismatches(shipmentId)` |
| Field corrected | same as confirmed |
| Document deleted | `documentList`, `shipmentFields`, `shipmentProducts`, `shipmentMismatches` |

---

## 10. Upload Zone Component

### Accepted formats (for `<input accept="">`)
```
.pdf,.jpg,.jpeg,.png,.webp,.docx,.xls,.xlsx,.csv
```
Or by MIME type:
```
application/pdf,image/jpeg,image/png,image/webp,
application/vnd.openxmlformats-officedocument.wordprocessingml.document,
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,
application/vnd.ms-excel,text/csv
```

### File icon mapping (for document list)
```typescript
const FILE_ICONS: Record<string, string> = {
  'application/pdf': 'FileText',
  'image/jpeg': 'Image',
  'image/png': 'Image',
  'image/webp': 'Image',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'FileType',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Table',
  'application/vnd.ms-excel': 'Table',
  'text/csv': 'Table',
};
```

### Upload flow

```
User drops / selects file(s)
  ↓
Validate client-side: extension, size < 1 GB
  ↓
POST /documents/upload (single) or /documents/upload/batch
  ↓
Show uploading spinner per file
  ↓
On 201 → begin polling GET /documents/{id} every 3s
  ↓
Poll until status ∉ ['uploaded', 'ocr_pending', 'ocr_processing']
  ↓
On 'classified' / 'matched' → show "Processing complete" toast
On 'ocr_failed' → show error toast "Could not read file"
On 'needs_review' → show amber warning "Low confidence classification"
  ↓
Navigate to Document Detail or Shipment Detail (if shipment_id is set)
```

---

## 11. Document Detail Page

### Header
- Filename, file type badge, status badge, uploaded date
- Download button (uses `download_url` from `GET /documents/{id}`)

### "Products" tab  ← **NEW**
Source: `GET /api/v1/documents/{document_id}/products`

Table columns:
| Column | Notes |
|---|---|
| Product Name | `product_name` |
| HS Code | `existing_hs_code` — monospace chip |
| Quantity | `quantity` |
| Unit Price | `unit_price` + `currency` |
| Origin → Destination | `origin_country` → `destination_country` with flag emoji |
| Ready? | Green tick or amber "Missing: material, intended_use" |

Empty state: "No products extracted" (shown while processing, or if doc has no product lines)

### "Fields" tab  ← **updated**
Source: `GET /api/v1/documents/{document_id}/fields`

Group rows by `field_name`. For each field:
- Display label (from Field Name Reference table)
- `value_normalized ?? value_raw`
- Confidence badge (green ≥ 0.85, amber 0.70–0.84, red < 0.70)
- Status badge
- "Confirm" / "Correct" buttons

Corrected fields: strike through `value_raw`, show `corrected_value` in green.

---

## 12. Shipment Detail — Fields Tab

### Layout
Three sub-sections stacked vertically:

#### 12.1 Mismatches banner (only when mismatches exist)
Source: `GET /api/v1/shipments/{id}/field-mismatches`

```
┌──────────────────────────────────────────────────────────┐
│ ⚠ 2 field conflicts detected across documents            │
│                                                          │
│ [error] gross_weight                                     │
│   • Invoice (invoicem_123.pdf): 830 kg                   │
│   • Packing List (pl_456.pdf): 792 kg                    │
│                                                          │
│ [warning] party_consignee                                │
│   • Invoice: SAN WOJ                                     │
│   • Packing List: San Woj Ltd                            │
└──────────────────────────────────────────────────────────┘
```

- `severity=error`: red border, `AlertOctagon` icon
- `severity=warning`: amber border, `AlertTriangle` icon
- Each value row shows the document filename (link to document detail) + the value
- A "Review" chip links to the corresponding field in the Fields table below

#### 12.2 Products table
Source: `GET /api/v1/shipments/{id}/products`

Same columns as Document Detail Products tab, with an extra "Source Document" column showing the filename chip.

Group by `document_id` — show a separator row per document with the filename as a sticky sub-header.

#### 12.3 Extracted fields table
Source: `GET /api/v1/shipments/{id}/fields`

Group by `field_name`. For each unique field name:
- If all docs agree → single value chip
- If docs disagree → multiple chips, each labelled with the source filename; highlight in red (error) or amber (warning) per mismatch severity
- Confirm / Correct per individual field record (expanded row)

---

## 13. Business Rules

1. **Polling timeout**: stop polling after 10 minutes. Show "Processing timed out" error state.
2. **Retry on error**: if `status = 'ocr_failed'`, show a "Retry" button that re-triggers processing (call `DELETE /documents/{id}` then re-upload, or contact backend).
3. **Products are per-document**: `DocumentProduct` records are tied to a `document_id`. If a document is deleted, its products disappear.
4. **invoice_number auto-linking**: after status transitions to `matched`, `document.shipment_id` is set. Navigate to the shipment or show a "Grouped into Shipment #…" pill on the document card.
5. **Zero-tolerance mismatch fields**: `gross_weight`, `net_weight`, `currency`, `hs_code`, `invoice_value`, `stated_origin` — any discrepancy is `error` severity regardless of org settings.
6. **`is_ready_to_classify = false`**: show an amber chip listing `missing_required_fields` so the user knows what information to provide before the product can be HS-classified.
7. **Confidence display**: always show raw confidence as a percentage tooltip. Use colour bands (green/amber/red) for quick scanning.
