# Document Upload & Extraction — Frontend Spec

> **Purpose**: Complete guide for the frontend to implement the document/shipment flow. Supersedes any earlier document-upload or field-extraction sections in `FRONTEND_SPEC.md`.

---

## 0. High-Level Flow

The new flow is **shipment-first**. The user creates a shipment before uploading documents.

```
1. User creates shipment (enters invoice number)
        ↓
2. User uploads one or more documents to that shipment
        ↓
3. System OCRs + classifies each document
   • High confidence → doc_type set automatically
   • Low confidence  → frontend shows type picker, user selects
        ↓
4. System extracts fields + products per document
        ↓
5. User reviews & confirms extracted fields per document
        ↓
6. Mismatch banner appears (only when ≥ 2 documents with same fields disagree)
```

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

Max file size: **1 GB**. Max batch: **15 files**.

---

## 2. Document Types (for manual selection picker)

When the system cannot classify a document with confidence ≥ 70%, the frontend must show a picker. These are the 8 types the user can choose from:

| `doc_type` value | Display label |
|---|---|
| `commercial_invoice` | Commercial Invoice |
| `packing_list` | Packing List |
| `bill_of_material` | Bill of Material |
| `bill_of_lading` | Bill of Lading |
| `certificate_of_origin` | Certificate of Origin |
| `phytosanitary_certificate` | Phytosanitary Certificate |
| `product_specification` | Product Specification |
| `air_waybill` | Airway Bill |

---

## 3. TypeScript Types

```typescript
// ── Document types ────────────────────────────────────────────────────────────
type DocumentStatus =
  | 'uploaded' | 'ocr_pending' | 'ocr_processing' | 'ocr_failed'
  | 'classified' | 'matched' | 'unmatched' | 'needs_review';

type DocumentSource = 'upload' | 'email';

type DocType =
  | 'commercial_invoice' | 'packing_list' | 'bill_of_material'
  | 'bill_of_lading' | 'certificate_of_origin' | 'phytosanitary_certificate'
  | 'product_specification' | 'air_waybill'
  | 'insurance_certificate' | 'customs_declaration' | 'purchase_order'
  | 'delivery_order' | 'mill_certificate' | 'suppliers_declaration'
  | 'cmr' | 'other';

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

// ── Shipment types ────────────────────────────────────────────────────────────
type ShipmentStatus = 'active' | 'on_hold' | 'complete';
type ReferenceType = 'invoice' | 'bl' | 'awb' | 'po' | 'container' | 'internal';

interface ShipmentReference {
  id: string;
  ref_type: ReferenceType;
  ref_value: string;
}

interface DocumentSummary {
  id: string;
  filename: string;
  status: DocumentStatus;
  doc_type: DocType | null;
  doc_type_confidence: number | null;   // 0.0–1.0
  is_manual_override: boolean | null;
  field_count: number;
  confirmed_field_count: number;
  product_count: number;
}

interface ShipmentDetail {
  id: string;
  org_id: string;
  status: ShipmentStatus;
  created_at: string;
  updated_at: string;
  references: ShipmentReference[];
  documents: DocumentSummary[];
}

// ── Field types ───────────────────────────────────────────────────────────────
type ExtractedFieldStatus = 'extracted' | 'confirmed' | 'corrected';
type FieldType = 'string' | 'decimal' | 'date' | 'iso_code';

interface ExtractedField {
  id: string;
  document_id: string;
  shipment_id: string | null;
  org_id: string | null;
  field_name: string;
  value_raw: string;
  value_normalized: string | null;
  field_type: FieldType | null;
  confidence: number;
  page_number: number | null;
  status: ExtractedFieldStatus;
  confirmed_at: string | null;
  confirmed_by: string | null;
  corrected_value: string | null;
  corrected_by: string | null;
  corrected_at: string | null;
  created_at: string;
}

// ── Product types ─────────────────────────────────────────────────────────────
interface DocumentProduct {
  id: string;
  document_id: string;
  shipment_id: string | null;
  org_id: string;
  product_name: string | null;
  material: string | null;
  intended_use: string | null;
  description: string | null;
  quantity: string | null;
  unit_price: string | null;
  currency: string | null;
  origin_country: string | null;
  destination_country: string | null;
  existing_hs_code: string | null;
  missing_required_fields: string[] | null;
  is_ready_to_classify: boolean;
  created_at: string;
}

// ── Mismatch types ────────────────────────────────────────────────────────────

// Shipment-level field mismatch (same field disagrees across documents)
interface MismatchValue {
  document_id: string;
  value_raw: string;
  value_normalized: string | null;
  confidence: number;
}

interface FieldMismatch {
  field_name: string;
  severity: 'error' | 'warning';
  values: MismatchValue[];
}

// Product-level mismatch (same product matched across documents, field differs)
interface ProductMismatchValue {
  document_id: string;
  product_id: string;
  product_name: string | null;
  value: string;
}

interface ProductFieldMismatch {
  field_name: string;          // "quantity" | "unit_price" | "existing_hs_code" | "currency" | "origin_country" | "destination_country"
  display_label: string;       // "Quantity" | "Unit Price" | "HS Code" | …
  severity: 'error' | 'warning';
  values: ProductMismatchValue[];
}

interface ProductGroupMismatch {
  product_key: string;         // HS code or product name used to match across docs
  hs_code: string | null;      // set when matching was hs-based
  field_mismatches: ProductFieldMismatch[];
}

// Product present in one document but absent from another doc that has products
interface UnmatchedProduct {
  document_id: string;         // the document that HAS this product
  product_id: string;
  product_name: string | null;
  hs_code: string | null;
  quantity: string | null;
  unit_price: string | null;
  currency: string | null;
  missing_in: string[];        // document_ids that have products but NOT this one
}

interface ShipmentMismatchOut {
  shipment_id: string;
  mismatches: FieldMismatch[];                   // shipment-level field conflicts
  product_mismatches: ProductGroupMismatch[];    // matched products with differing fields
  unmatched_products: UnmatchedProduct[];        // products with no counterpart in other docs
}
```

---

## 4. API Reference

All endpoints are prefixed with `/api/v1`. Auth: `Authorization: Bearer <token>` on every call.

### 4.1 Shipments

#### Create shipment  ← **NEW**
```
POST /api/v1/shipments/
Content-Type: application/json

{ "invoice_number": "INV-2026-001" }
```
**Response**: `201 ShipmentDetail` (with empty `documents` array)

**Errors**:
- `409` — a shipment with that invoice number already exists in the org
- `422` — invoice_number is blank

#### List shipments
```
GET /api/v1/shipments/
```
**Response**: `200 ShipmentOut[]` (lightweight, no document list)

#### Get shipment detail  ← **updated response**
```
GET /api/v1/shipments/{shipment_id}
```
**Response**: `200 ShipmentDetail` — includes `documents[]` with per-document field/product counts

#### Update shipment status
```
PATCH /api/v1/shipments/{shipment_id}
Body: { "status": "active" | "on_hold" | "complete" }
```
**Response**: `200 ShipmentOut`

#### Delete shipment
```
DELETE /api/v1/shipments/{shipment_id}
```
**Response**: `204`

---

### 4.2 Document Upload

#### Single upload  ← **updated: accepts shipment_id**
```
POST /api/v1/documents/upload
Content-Type: multipart/form-data

Field: file        (binary, required)
Field: shipment_id (UUID string, optional)
```
**Response**: `201 DocumentOut`

When `shipment_id` is provided, the document is immediately linked to that shipment. OCR + extraction still run automatically.

#### Batch upload  ← **updated: accepts shipment_id**
```
POST /api/v1/documents/upload/batch
Content-Type: multipart/form-data

Field: files[]     (binary, repeated, required)
Field: shipment_id (UUID string, optional — applies to ALL files in batch)
```
**Response**: `201 DocumentOut[]`

**Errors**:
- `413` — file exceeds 1 GB
- `415` — unsupported extension
- `400` — batch exceeds 15 files

---

### 4.3 Document Queries

#### Get single document + presigned download URL
```
GET /api/v1/documents/{document_id}
```
**Response**: `200 DocumentOut` (includes `download_url`, valid 1 hour)

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

### 4.4 Document Type Classification

#### Get classification for a document
```
GET /api/v1/classifications/{document_id}
```
**Response**:
```json
{
  "id": "...",
  "document_id": "...",
  "doc_type": "commercial_invoice",
  "confidence": 0.92,
  "is_manual_override": false,
  "classified_by": null,
  "classified_at": "2026-07-16T10:00:00Z"
}
```

#### Override / set document type manually (user selection)
```
POST /api/v1/classifications/{document_id}/override
Body: { "doc_type": "bill_of_material" }
```
**Response**: `200 ClassificationOut`

After override, the pipeline re-runs shipment matching automatically.

---

### 4.5 Extracted Fields

#### Fields for one document
```
GET /api/v1/documents/{document_id}/fields
```
**Response**: `200 ExtractedField[]`

#### Fields for a shipment (all documents merged)
```
GET /api/v1/shipments/{shipment_id}/fields
```
**Response**: `200 ExtractedField[]`

#### Confirm a field
```
POST /api/v1/fields/{field_id}/confirm
```
**Response**: `200 ExtractedField`

#### Correct a field
```
POST /api/v1/fields/{field_id}/correct
Body: { "corrected_value": "string" }
```
**Response**: `200 ExtractedField`

#### Confirm all fields for a shipment  ← **NEW**
```
POST /api/v1/shipments/{shipment_id}/fields/confirm-all
```
Optional query param: `?document_id={uuid}` to confirm only one document's fields.

**Response**: `200 { "confirmed": 12 }`

Skips fields already in `confirmed` or `corrected` status.

---

### 4.6 Document Products

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

### 4.7 Cross-Document Mismatch Detection

Compares extracted values across all documents in a shipment. Returns empty arrays when fewer than 2 documents are present.

```
GET /api/v1/shipments/{shipment_id}/field-mismatches
```
**Response**: `200 ShipmentMismatchOut`

Three sections in the response:

**`mismatches`** — shipment-level fields that conflict across documents:

| field_name | severity |
|---|---|
| `gross_weight` | **error** |
| `net_weight` | **error** |
| `currency` | **error** |
| `stated_origin` | **error** |
| `invoice_date` | **error** |
| `destination_country` | warning |
| `incoterm` | warning |
| `party_shipper` | warning |
| `party_consignee` | warning |
| `place_of_loading` | warning |
| `port_of_discharge` | warning |

**`product_mismatches`** — products matched across documents (by HS code or name) where a field differs. Fields compared:

| field_name | display_label | severity |
|---|---|---|
| `existing_hs_code` | HS Code | **error** |
| `quantity` | Quantity | **error** |
| `unit_price` | Unit Price | **error** |
| `currency` | Currency | **error** |
| `origin_country` | Country of Origin | warning |
| `destination_country` | Destination Country | warning |

**`unmatched_products`** — products present in one document but with no matching product in another document that has products. These indicate a coverage gap (e.g. packing list has a product the invoice doesn't).

---

## 5. Field Name Reference

All `field_name` values in `ExtractedField.field_name`:

| field_name | Display label | Type |
|---|---|---|
| `party_shipper` | Seller / Consignor | string |
| `vat_number_seller` | Seller VAT / EIK | string |
| `rex_number_seller` | Seller REX Number | string |
| `party_consignee` | Buyer / Consignee | string |
| `vat_number_buyer` | Buyer VAT Number | string |
| `rex_number_buyer` | Buyer REX Number | string |
| `eori_number` | EORI Number | string |
| `invoice_value` | Invoice Value | decimal |
| `vat_value` | VAT Amount | decimal |
| `freight_value` | Freight Value | decimal |
| `insurance_value` | Insurance Value | decimal |
| `currency` | Currency | iso_code |
| `gross_weight` | Gross Weight | decimal |
| `net_weight` | Net Weight | decimal |
| `quantity` | Quantity | decimal |
| `total_packages` | Total Packages | decimal |
| `hs_code` | HS / Commodity Code | string |
| `commodity_description` | Product Description | string |
| `lot_number` | Lot Number | string |
| `product_registration_number` | Product Reg. No. | string |
| `product_serial_number` | Serial Number | string |
| `stated_origin` | Country of Origin | iso_code |
| `destination_country` | Destination Country | iso_code |
| `place_of_loading` | Place of Loading | string |
| `incoterm` | Incoterm | iso_code |
| `preferential_duty` | Preferential Duty | string |
| `invoice_date` | Invoice Date | date |
| `due_date` | Payment Due Date | date |
| `shipment_date` | Shipment Date | date |
| `expiry_date` | Expiry Date | date |
| `reference` | Reference / Invoice No. | string |
| `local_reference` | Local Reference | string |
| `point_of_entry` | Point of Entry | string |

**Display rules**:
- `decimal`: show `value_normalized` (pure number); append unit/currency label.
- `date`: show `value_normalized` (YYYY-MM-DD) formatted to locale.
- `iso_code`: show flag + code (e.g. 🇬🇧 GBP).
- `preferential_duty`: highlighted info box with full statement text.
- `eori_number`, `vat_number_*`, `rex_number_*`: monospace pill.
- Confidence < 0.70: amber badge "Low confidence".
- `status = 'corrected'`: show `corrected_value`, strike through `value_raw`.

---

## 6. API Functions (`src/api/`)

### `src/api/shipments.ts`

```typescript
import { api } from './client';
import type { ShipmentDetail, ShipmentOut } from '../types';

export const shipmentsApi = {
  create: (invoiceNumber: string) =>
    api.post<ShipmentDetail>('/shipments/', { invoice_number: invoiceNumber }).then(r => r.data),

  list: () =>
    api.get<ShipmentOut[]>('/shipments/').then(r => r.data),

  get: (shipmentId: string) =>
    api.get<ShipmentDetail>(`/shipments/${shipmentId}`).then(r => r.data),

  updateStatus: (shipmentId: string, status: string) =>
    api.patch<ShipmentOut>(`/shipments/${shipmentId}`, { status }).then(r => r.data),

  delete: (shipmentId: string) =>
    api.delete(`/shipments/${shipmentId}`),
};
```

### `src/api/documents.ts`

```typescript
import { api } from './client';
import type { DocumentOut } from '../types';

export const documentsApi = {
  upload: (file: File, shipmentId?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (shipmentId) form.append('shipment_id', shipmentId);
    return api.post<DocumentOut>('/documents/upload', form).then(r => r.data);
  },

  uploadBatch: (files: File[], shipmentId?: string) => {
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    if (shipmentId) form.append('shipment_id', shipmentId);
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
  getForDocument: (documentId: string) =>
    api.get<ExtractedField[]>(`/documents/${documentId}/fields`).then(r => r.data),

  getForShipment: (shipmentId: string) =>
    api.get<ExtractedField[]>(`/shipments/${shipmentId}/fields`).then(r => r.data),

  confirm: (fieldId: string) =>
    api.post<ExtractedField>(`/fields/${fieldId}/confirm`).then(r => r.data),

  correct: (fieldId: string, correctedValue: string) =>
    api.post<ExtractedField>(`/fields/${fieldId}/correct`, { corrected_value: correctedValue })
       .then(r => r.data),

  confirmAll: (shipmentId: string, documentId?: string) =>
    api.post<{ confirmed: number }>(
      `/shipments/${shipmentId}/fields/confirm-all`,
      {},
      { params: documentId ? { document_id: documentId } : {} }
    ).then(r => r.data),

  getProductsForDocument: (documentId: string) =>
    api.get<DocumentProduct[]>(`/documents/${documentId}/products`).then(r => r.data),

  getProductsForShipment: (shipmentId: string) =>
    api.get<DocumentProduct[]>(`/shipments/${shipmentId}/products`).then(r => r.data),

  getMismatches: (shipmentId: string) =>
    api.get<ShipmentMismatchOut>(`/shipments/${shipmentId}/field-mismatches`).then(r => r.data),
};
```

### `src/api/classifications.ts`

```typescript
import { api } from './client';

interface ClassificationOut {
  id: string;
  document_id: string;
  doc_type: string;
  confidence: number;
  is_manual_override: boolean;
  classified_by: string | null;
  classified_at: string;
}

export const classificationsApi = {
  get: (documentId: string) =>
    api.get<ClassificationOut>(`/classifications/${documentId}`).then(r => r.data),

  override: (documentId: string, docType: string) =>
    api.post<ClassificationOut>(`/classifications/${documentId}/override`, { doc_type: docType })
       .then(r => r.data),
};
```

---

## 7. Query Keys

```typescript
export const queryKeys = {
  shipmentList: () => ['shipments'] as const,
  shipment: (id: string) => ['shipment', id] as const,

  documentList: (shipmentId?: string) => ['documents', shipmentId] as const,
  document: (id: string) => ['document', id] as const,

  classification: (documentId: string) => ['classification', documentId] as const,

  documentFields: (documentId: string) => ['fields', 'document', documentId] as const,
  shipmentFields: (shipmentId: string) => ['fields', 'shipment', shipmentId] as const,

  documentProducts: (documentId: string) => ['products', 'document', documentId] as const,
  shipmentProducts: (shipmentId: string) => ['products', 'shipment', shipmentId] as const,

  shipmentMismatches: (shipmentId: string) => ['mismatches', shipmentId] as const,
};
```

---

## 8. Query Invalidation Rules

| Event | Invalidate |
|---|---|
| Shipment created | `shipmentList` |
| Shipment status changed | `shipment(id)` |
| Document uploaded | `shipment(shipmentId)`, `documentList(shipmentId)` |
| Document polling → status changed | `document(id)`, `shipment(shipmentId)` |
| Document type overridden | `classification(documentId)`, `shipment(shipmentId)` |
| Field confirmed / corrected | `documentFields(documentId)`, `shipmentFields(shipmentId)`, `shipmentMismatches(shipmentId)`, `shipment(shipmentId)` |
| confirm-all | same as field confirmed |
| Document deleted | `documentList`, `shipment(shipmentId)`, `shipmentFields`, `shipmentProducts`, `shipmentMismatches` |

---

## 9. Page Designs

### 9.1 Create Shipment Dialog / Page

A simple form with one input:

```
Invoice Number *  [ INV-2026-001        ]
                  [ Create Shipment     ]
```

On submit: call `POST /shipments/`. On success navigate to Shipment Detail page.

Error case: `409` → show inline error "A shipment with this invoice number already exists."

---

### 9.2 Shipment Detail Page

**Header**: Invoice reference chip, status badge (`active` / `on_hold` / `complete`), created date, Edit Status dropdown.

**Mismatch Banner** (shown only when any mismatch array is non-empty):
```
┌──────────────────────────────────────────────────────────┐
│ ⚠ 3 conflicts detected                                   │
│                                                          │
│ SHIPMENT-LEVEL                                           │
│ [error]   Gross Weight                                   │
│   • invoicem_123.pdf : 830 kg                            │
│   • pl_456.pdf       : 792 kg                            │
│                                                          │
│ PRODUCT-LEVEL — Paneer 1kg Block (HS 0406.10)            │
│ [error]   Quantity                                       │
│   • invoicem_123.pdf : 100 kg                            │
│   • pl_456.pdf       : 98 kg                             │
│                                                          │
│ UNMATCHED PRODUCTS                                       │
│ [warning] "Ghee" found in invoicem_123.pdf               │
│           not present in pl_456.pdf                      │
└──────────────────────────────────────────────────────────┘
```
- Only call `GET /shipments/{id}/field-mismatches` when `documents.length >= 2`.
- `severity=error` → red border + `AlertOctagon` icon.
- `severity=warning` → amber border + `AlertTriangle` icon.
- Total conflict count = `mismatches.length + product_mismatches.length + unmatched_products.length`.

**Document List** (source: `ShipmentDetail.documents`):

Each row in the list:
| Column | Source |
|---|---|
| Filename + type icon | `filename`, `content_type` |
| Document type badge | `doc_type` (see §2 display labels) |
| Confidence | `doc_type_confidence` as % — amber if < 70% |
| Status badge | `status` |
| Fields | `confirmed_field_count` / `field_count` (e.g. "8 / 12") |
| Products | `product_count` |
| Actions | View, Delete |

**Type picker (shown when `status === 'needs_review'` or `doc_type === null`):**

```
What type is this document?
[ Commercial Invoice ] [ Packing List ] [ Bill of Material ]
[ Bill of Lading    ] [ Cert. Origin ] [ Phytosanitary    ]
[ Product Spec      ] [ Airway Bill  ]
```

On selection: call `POST /classifications/{documentId}/override`. Invalidate `classification(documentId)` and `shipment(shipmentId)`.

**Upload Zone** (always visible at the bottom of the document list):

```
[ Drop files here or click to browse ]
PDF  JPG  PNG  WEBP  DOCX  XLSX  CSV
```

Uploaded files are immediately linked to the current shipment (pass `shipment_id` in the form).

---

### 9.3 Document Detail Page

**Header**: Filename, type badge, status badge, uploaded date, Download button.

**Tab: Products** (source: `GET /documents/{id}/products`)

Table:
| Product Name | HS Code | Qty | Unit Price | Origin → Dest | Ready? |
|---|---|---|---|---|---|
| Eco Bag | 6305.33 | 1kg | 5.20 GBP | 🇧🇬 BG → 🇬🇧 GB | ✅ |
| (no name) | — | — | — | — | ⚠ Missing: material |

**Tab: Fields** (source: `GET /documents/{id}/fields`)

Grouped by field_name. For each field row:
- Display label
- `value_normalized ?? value_raw`
- Confidence badge (green ≥ 0.85, amber 0.70–0.84, red < 0.70)
- Status badge (`extracted` / `confirmed` / `corrected`)
- Confirm button (if `status === 'extracted'`)
- Correct button (opens inline text input)

"Confirm All" button at top right → calls `POST /shipments/{id}/fields/confirm-all?document_id={id}`.

Progress indicator: `8 / 12 fields confirmed`.

Corrected fields: show `corrected_value` in green, strike through `value_raw`.

---

## 10. Upload Component

### `<input accept="">` string
```
.pdf,.jpg,.jpeg,.png,.webp,.docx,.xls,.xlsx,.csv
```

### Upload flow (when inside Shipment Detail)

```
User drops / selects file(s)
  ↓
Client validates: extension, size < 1 GB
  ↓
POST /documents/upload (or /upload/batch) with shipment_id in form
  ↓
Show per-file uploading spinner
  ↓
On 201 → invalidate shipment(id), documentList(shipmentId)
  ↓
Begin polling GET /documents/{id} every 3s
  ↓
Poll until status ∉ ['uploaded', 'ocr_pending', 'ocr_processing']
  ↓
status === 'needs_review' → show type picker for that document
status === 'classified' / 'matched' → show success, refresh shipment
status === 'ocr_failed' → show error "Could not read file. Try again."
  ↓
Stop polling after 10 minutes → show "Processing timed out"
```

### File icon mapping

```typescript
const FILE_ICONS: Record<string, string> = {
  'application/pdf': 'FileText',
  'image/jpeg': 'Image', 'image/png': 'Image', 'image/webp': 'Image',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'FileType',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Table',
  'application/vnd.ms-excel': 'Table',
  'text/csv': 'Table',
};
```

---

## 11. Business Rules

1. **Shipment is created first** — the user always creates a shipment before uploading documents.
2. **Document type is required before field confirmation is meaningful** — if `doc_type` is null, nudge the user to set it first.
3. **Mismatch engine only runs with ≥ 2 documents** — hide the mismatch banner entirely when `documents.length < 2`.
4. **Field confirmation is per document** — "Confirm All" on a document confirms only that document's fields. The shipment-level confirm-all confirms every document in the shipment.
5. **Products are per document** — if a document is deleted, its products disappear.
6. **`is_ready_to_classify = false`** — show amber chip "Missing: material, intended_use" so the user knows what to add before HS classification.
7. **`invoice_number` deduplication** — creating two shipments with the same invoice number is rejected (`409`). This prevents accidental duplicate shipments.
8. **Polling timeout** — 10 minutes max. Show "Processing timed out — please re-upload the file."
9. **Confidence thresholds**:
   - ≥ 0.85 → green
   - 0.70–0.84 → amber
   - < 0.70 → red + "Needs review"

---

## 12. Migration Checklist (What Changed vs Old Flow)

| # | What to change | Section |
|---|---|---|
| 1 | **New page/flow**: Create Shipment form before upload | §9.1 |
| 2 | Upload endpoints now accept `shipment_id` form field | §4.2 |
| 3 | Extend file accept to WEBP/DOCX/XLSX/CSV | §10 |
| 4 | `GET /shipments/{id}` now returns `ShipmentDetail` with `documents[]` | §4.1 |
| 5 | New document type picker when `status === 'needs_review'` | §9.2 |
| 6 | New `POST /shipments/` create endpoint | §4.1 |
| 7 | New "Products" tab on Document Detail | §9.3 |
| 8 | New "Confirm All" button per document | §9.3 |
| 9 | Mismatch banner: only shown when ≥ 2 docs | §9.2 |
| 10 | Add `bill_of_material` + `product_specification` to doc type picker | §2 |
| 11 | New query keys + invalidation rules | §7, §8 |
