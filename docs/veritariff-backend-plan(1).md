# Veritariff — Backend Plan (FastAPI / Python), 6 Weeks

**Stack (decided):** FastAPI + Pydantic v2 · PostgreSQL + SQLAlchemy 2.0 + Alembic · Celery + Redis (or ARQ if you're already async-everywhere) · S3-compatible object storage · LLM structured extraction via API (Claude/GPT, JSON-schema output) · `rapidfuzz` for name matching · pytest.

**The four laws (enforced in code review):**
1. Flag, don't guess — no silent defaults, no fallback values.
2. Provenance on everything — every field has `document_id`, `page_number`, `confidence`. Non-nullable.
3. LLM extracts and phrases only. All comparison/tolerance/matching decisions are pure, deterministic, unit-tested Python. Zero LLM calls inside the mismatch engine.
4. Never dead-end — every failure state returns what's missing and what the user can do.

---

## Repo layout

```
app/
  api/            # routers (thin — no business logic)
    shipments.py, documents.py, fields.py, flags.py, ingest.py, settings.py
  core/           # config, security, deps
  models/         # SQLAlchemy models
  schemas/        # Pydantic (request/response + extraction schemas per doc type)
  services/
    ingestion/    # email intake, upload, tabular (xls/csv/xml) parsing
    classification/  # doc-type classifier wrapper
    extraction/   # LLM extraction, validators, normalization
    matching/     # shipment matcher (refs + name/date fallback)
    mismatch/     # comparison engine, tolerance model, fuzzy names  ← PURE PYTHON
    suggestions/  # deterministic suggestion heuristics
  workers/        # celery tasks: ingest → classify → extract → compare
  tests/
    unit/  integration/  eval/   # eval = accuracy harness w/ labelled ground truth
alembic/
```

Rule: `services/mismatch/` and `services/suggestions/` import nothing from `extraction/` and make no network calls. If a PR adds an HTTP client there, reject it.

---

## Data model (Sprint 0 — Alembic migration)

Tables: `shipments`, `documents`, `extracted_fields`, `product_records`, `flags`, `flag_resolutions`, `audit_log`, `org_settings`.

Key constraints that encode the product laws:
- `extracted_fields.document_id` **NOT NULL** (provenance is structural, not conventional)
- `extracted_fields.value_raw` never updated — corrections write `status='reviewed_corrected'` + a new normalized value + `reviewed_by/at`
- `flag_resolutions` is append-only: no UPDATE/DELETE grants for the app role on that table (this is the corpus)
- `flags.type` enum includes `hs_inconsistency` now (reserved, unused) so post-MVP wiring is additive
- Enums as PG enums; thresholds in `org_settings` JSONB with a documented default: `{"weight_qty_tolerance_pct": 0.5, "value_tolerance_pct": 1.0, "name_match_threshold": 0.93}`

Canonical field names as a Python `StrEnum` (`PARTY_SHIPPER`, `INVOICE_VALUE`, `CURRENCY`, `GROSS_WEIGHT`, `NET_WEIGHT`, `QUANTITY`, `HS_CODE`, `STATED_ORIGIN`, `INCOTERM`, `INVOICE_DATE`, `SHIPMENT_DATE`, `REFERENCE`) — shared by extraction schemas, the comparison engine, and the API. One source of truth.

---

## Pipeline (Celery chain per document)

```
ingest(document) → classify(document) → extract(document) → compare(shipment)
```

- Each task idempotent, keyed on `document_id`; `compare` debounced per shipment (re-run when any doc/field changes).
- Failure at any stage → document status `failed_<stage>` + a `Flag` explaining what to do (retry, unsupported format, etc.). Loud, never silent.
- Duplicate detection at ingest: SHA-256 of file bytes per shipment; duplicate → linked, not re-processed.

---

## Sprint 0 (Week 1)

| # | Ticket | DoD |
|---|---|---|
| B0.1 | Alembic migration to full schema + backfill script for existing BrokerAI docs | Runs on staging copy, zero loss, rollback tested |
| B0.2 | Extend classifier taxonomy: mill certificate, supplier's declaration, CMR | ≥85% on a 20-doc eval set per new type |
| B0.3 | Tabular ingestion path: XLS/CSV (`openpyxl`/`pandas`) and XML (`lxml`) → skips OCR, goes straight to extraction | Sample files of each format flow to `extracted` |
| B0.4 | Shipment matcher fallback: normalized party name + ±5-day date window when refs absent/conflict; ambiguous → `needs_review` | Unit tests incl. the ambiguous case — never silent assignment |
| B0.5 | Run one real steel shipment set end-to-end through ingest+classify | Gaps documented as tickets |

**Gate:** B0.1 + B0.5. No real documents by Wednesday → escalate to founders.

## Sprint 1 (Weeks 2–3) — Extraction

| # | Ticket | DoD |
|---|---|---|
| B1.1 | Extraction service: per-doc-type Pydantic schema → LLM structured output → `ExtractedField[]` with page + confidence; retries, timeout, `failed_extraction` state | All fields carry provenance; malformed LLM output never reaches the DB (Pydantic gate) |
| B1.2 | Deterministic validators: Σ(line items)≈total, currency ∈ ISO 4217, incoterm ∈ Incoterms 2020, dates/units parse, weight sanity (net ≤ gross) | Validator failure downgrades confidence + attaches machine-readable reason |
| B1.3 | Normalization: `value_raw` → typed `value_normalized` (Decimal, ISO codes/dates, canonical units kg/pcs) | Property-based tests (`hypothesis`) on parsers; raw always preserved |
| B1.4 | Review endpoints: `GET /shipments/{id}/fields`, `POST /fields/{id}/confirm`, `POST /fields/{id}/correct` | Corrections audit-logged; correcting re-triggers `compare` |
| B1.5 | Record reuse: on extraction, lookup `product_records` by SKU/description-hash; attach recall payload (never auto-apply) | Confirm endpoint writes new `product_record` linkage |
| B1.6 | Missing-field flags from per-doc-type required-field map | `Flag(missing_field)` created |
| B1.7 | **Eval harness:** `tests/eval/` — 10 labelled shipments, per-field precision + flag-coverage report, runs in CI | Baseline recorded |

**Sprint gate (the number that matters):** ≥95% of *incorrect* extractions carry low confidence. Tune thresholds to over-flag. High-confidence accuracy ≥90% is secondary.

## Sprint 2 (Weeks 4–5) — Mismatch engine

| # | Ticket | DoD |
|---|---|---|
| B2.1 | Expected-document model: config-driven profile (V1: steel import) → `Flag(missing_document)`; comparisons needing it emit "cannot compare — X missing" | Pure config, no code change to add a profile |
| B2.2 | Comparison core: gather fields by canonical name across docs → rule dispatch. Pure functions, no I/O | 100% branch coverage on the rule dispatcher |
| B2.3 | Tolerance model: zero-tolerance (HS, origin, currency → severity `critical`); pct-band (weight/qty/value, thresholds from `org_settings`); Decimal math only, never float | Boundary tests at exactly-threshold |
| B2.4 | Fuzzy names: normalize → legal-suffix dictionary (Ltd/Limited/GmbH/SA/BV/SRL…) → token-sort Jaro-Winkler (`rapidfuzz`), threshold from settings | 50 same-pairs / 50 different-pairs suite; **zero false merges** on different set |
| B2.5 | Flag API: `GET /shipments/{id}/flags?status=open` ranked by severity, each with `conflicting_values[{document_id, value_raw, page_number}]` | Deep-linkable to doc+page |
| B2.6 | Resolution: `POST /flags/{id}/resolve {decision, chosen_value, note}` → append-only `flag_resolutions` | DB role cannot UPDATE/DELETE the table |
| B2.7 | Low-confidence interaction: comparisons touching a low-confidence field return status `unverified`, not `mismatch`; field review re-runs compare | Integration test covers the full loop |

**Sprint gate:** seeded suite of 5 shipments with injected faults (wrong currency, +2% weight, name variant, missing packing list) — 100% of zero-tolerance faults caught, tolerance applied correctly, name variant not flagged, missing doc reported.

## Sprint 3 (Week 6) — Suggestions, status, hardening

| # | Ticket | DoD |
|---|---|---|
| B3.1 | Suggestion heuristics (deterministic): majority-across-documents, source-priority (invoice for value, BL for weight) → `{value, cited_document_ids, rationale}`; accept endpoint = resolution logged | Never auto-applied |
| B3.2 | Shipment status machine: `ingesting → needs_review → flags_open → clear`; `clear` requires zero open flags AND zero unreviewed low-confidence fields | State-transition tests |
| B3.3 | Dashboard endpoints: attention queue, open-flag counts by severity, missing docs, pending reviews | Single aggregate endpoint, <300ms on seed data |
| B3.4 | Hardening: chaos tests (kill worker mid-extraction, re-send same email, corrupt PDF) — loud degradation, idempotent recovery | All three scenarios pass |
| B3.5 | Full `audit_log` on user actions; OpenAPI docs complete for FE handoff | — |

---

## What most backend teams get wrong here

- **Float money/weights.** Use `Decimal` end-to-end or the tolerance model produces phantom mismatches and phantom passes. This bug alone can sink pilot trust.
- **Confidence as decoration.** The confidence score routes fields to review, suppresses comparisons, and drives the dashboard — it's control flow, not metadata. Sprint 1's real deliverable is a trustworthy confidence signal.
- **LLM leakage into decisions.** One "just ask the model if the names match" PR and the deterministic-engine positioning is dead and the audit trail is fiction. The import ban on `services/mismatch/` exists for this reason.
- **Mutable resolutions.** The append-only grant on `flag_resolutions` is the company's data moat expressed as a permission. Don't soften it for convenience.

---
---

# TRACK B — Trade Intelligence Module (Backend), Weeks 7–12

**Positioning decision (read before building):** this is NOT a standalone news platform. It is an intelligence layer joined to the Veritariff shipment corpus. The unit of value is not "an article" — it is **"an event matched to your HS codes, lanes, and parties."** Every architectural choice below flows from that. If a ticket makes sense for a generic news aggregator but doesn't touch the shipment join, it's deprioritized.

**Hard gate:** Track B does not start until the Track A MVP ship gate passes. One shared engineer max before that.

## Scope cuts (decided — the new PRD is a wishlist, not a spec)

| PRD item | Decision | Why |
|---|---|---|
| Personas: banks, investors, government agencies | **CUT** | Different buyers, different product. V1 personas = your existing three (broker/importer/exporter) |
| Reuters, FT, Politico licensed feeds | **CUT for V1** | Licensing costs 5–6 figures/yr and legal lead time; you cannot scrape them. Official sources (EC, WTO, HMRC, DBT, sanctions lists, TARIC updates) are free, authoritative, and *more* relevant to compliance users |
| Push notifications, Teams | **CUT** | Email + in-app only for V1. Slack later |
| Recommendation engine | **CUT** | Deterministic matching (HS/lane/party rules) beats a rec engine at this data volume — and it's citable ("shown because you have shipments on HS 7208 / TR→GB"), consistent with flag-don't-guess |
| Multilingual translation | Defer | English sources first; translation is an enrichment flag, not a launch blocker |
| 99.9% uptime, <2s dashboard | Rewrite | A news feed is not customs filing. 99.5%, best-effort freshness (hourly polls), honest SLOs |
| "AI-powered platform" | **Rename** | Same law as before: AI summarizes and classifies; matching to shipments is deterministic. The word does not appear in the product |

## Architecture additions

```
app/services/
  intel/
    sources/       # per-source adapters: RSS, HMRC/EC/WTO scrapers, sanctions lists
    enrichment/    # LLM: summarize, classify {countries, HS chapters/headings,
                   #   commodities, regulation type, event type}, impact score
    matching/      # DETERMINISTIC join: article entities × shipment corpus
                   #   (HS codes, lanes, party names via the SAME fuzzy matcher as Track A)
    alerts/        # digest builder, delivery (email + in-app)
    search/        # pgvector embeddings + hybrid keyword search
workers/intel/     # polling schedules (per-source cadence), enrichment queue
```

New tables: `intel_sources`, `intel_articles` (raw + hash dedup), `intel_enrichments` (summary, entities[], hs_codes[], countries[], regulation_refs[], impact_score, model_version), `intel_matches` (article_id × shipment_id/product_record_id × match_reason — **the join table is the product**), `user_interests` (explicit follows: HS codes, lanes, countries — seeded automatically from their shipment history), `alert_deliveries`.

Reuse, don't rebuild: the Track A fuzzy name matcher for party/sanctions matching; `org_settings` for alert prefs; the audit log.

## Sprints

### Sprint 4 (Weeks 7–8) — Ingestion + enrichment
| # | Ticket | DoD |
|---|---|---|
| B4.1 | Source adapters: 6–8 official sources (EC trade news, WTO, HMRC updates, DBT, UK/EU sanctions lists, TARIC amendment feed) with per-source poll cadence, dedup by content hash | Each source has a health check; a dead feed raises an ops flag, never silently stales |
| B4.2 | Enrichment pipeline: article → LLM structured output {summary ≤80 words, event_type, countries, HS chapters/headings (only when explicit or near-certain — **flag "unclassified" over guessing a code**), regulation refs, impact 1–5 with one-line rationale} | Pydantic-gated; `model_version` stored on every enrichment for later re-runs |
| B4.3 | Embeddings + pgvector index for semantic search | Hybrid (vector + keyword) query returns in <500ms on 10k articles |
| B4.4 | Eval set: 100 hand-labelled articles; classification precision report in CI | Baseline recorded; HS-code false-positive rate is the tracked number (a wrong HS match sends a false alarm to a user's shipment — worst failure mode) |

### Sprint 5 (Weeks 9–10) — The join + interests
| # | Ticket | DoD |
|---|---|---|
| B5.1 | Deterministic matcher: article entities × shipment corpus → `intel_matches` with machine-readable `match_reason` ("HS 7208 ∩ your product records", "lane TR→GB ∩ shipments #…", "party name ∩ sanctions list") | Pure Python, unit-tested, zero LLM calls — same law as the mismatch engine |
| B5.2 | Interest seeding: derive each org's interest profile from their shipment history (distinct HS headings, lanes, counterparties); explicit follow/unfollow endpoints on top | New shipment automatically extends the profile |
| B5.3 | Sanctions screening hook: party names on every ingested shipment screened against the sanctions-list source; hit → `Flag(sanctions_screen, severity=critical)` **in the Track A flag system** | This is the highest-value single feature in Track B — it lands in the existing compliance workflow, not the news feed |
| B5.4 | Feed + search APIs: `GET /intel/feed` (matched-first ranking), `GET /intel/search?q=`, `GET /shipments/{id}/intel` (events touching this shipment) | Every item carries `match_reason` + source link — citable, always |

### Sprint 6 (Weeks 11–12) — Alerts, assistant, admin
| # | Ticket | DoD |
|---|---|---|
| B6.1 | Alert engine: immediate email for critical matches (sanctions, safeguard/AD measures on followed HS+lane), daily digest otherwise; per-org prefs | Idempotent delivery, unsubscribe honored, `alert_deliveries` logged |
| B6.2 | Assistant endpoint: RAG over (matched articles + the org's shipment records) with mandatory citations; answers questions like "what changed for my steel imports this month"; **refuses legal-advice framing** — it summarizes and cites, never advises "you should reclassify" | Every claim in a response carries a source ref; no-source → "I can't find a basis for that" |
| B6.3 | Admin/ops: source health dashboard endpoints, enrichment re-run by `model_version`, per-source cost tracking | — |
| B6.4 | Load pass: 10k articles, 50 orgs, digest generation <5 min | — |

## Track B risks
- **HS misclassification of news → false alarms on shipments.** Mitigation: conservative extraction (unclassified > guessed), chapter-level matching before heading-level, and the false-positive metric as the Sprint 4 gate.
- **Source scraping fragility.** Official sites change markup without notice. Adapters isolated per source with health checks; one broken source never blocks the pipeline.
- **LLM cost creep on enrichment.** Cap: enrich once, store `model_version`, re-run only deliberately. Track per-source cost from day one (B6.3).
