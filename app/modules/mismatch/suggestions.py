"""
Suggestion heuristics for resolving field mismatches.
PURE PYTHON — no LLM, no network, no I/O.
"""
from dataclasses import dataclass, field


@dataclass
class Suggestion:
    field_name: str
    suggested_value: str
    cited_document_ids: list[str]
    rationale: str


# Source priority for each field: first doc_type in the list wins if that source is present.
SOURCE_PRIORITY: dict[str, list[str]] = {
    "invoice_value": ["COMMERCIAL_INVOICE", "PURCHASE_ORDER"],
    "gross_weight": ["BILL_OF_LADING", "AIR_WAYBILL", "PACKING_LIST"],
    "net_weight": ["BILL_OF_LADING", "AIR_WAYBILL", "PACKING_LIST"],
    "quantity": ["PACKING_LIST", "COMMERCIAL_INVOICE"],
    "hs_code": ["COMMERCIAL_INVOICE", "CUSTOMS_DECLARATION"],
    "stated_origin": ["CERTIFICATE_OF_ORIGIN", "COMMERCIAL_INVOICE"],
    "currency": ["COMMERCIAL_INVOICE"],
    "incoterm": ["COMMERCIAL_INVOICE"],
}


def generate_suggestions(
    fields: list,        # ExtractedField-like objects with: field_name, value_normalized/value_raw, document_id
    doc_types: dict,     # document_id (str or UUID) → doc_type string (upper-case)
    flag: object,        # Flag object with: field_name (str), conflicting_values (list | None)
) -> list[Suggestion]:
    """
    For a flag with conflicting values, generate suggestions using two strategies:

    Strategy 1 — Source priority:
        If the field has a source priority list and one source in that list has a value,
        suggest the value from the highest-priority source available.

    Strategy 2 — Majority vote:
        If >50% of sources agree on a value, suggest it with a majority rationale.

    Returns a list of Suggestion objects (may be empty).
    Never auto-applies any suggestion.
    """
    field_name: str = getattr(flag, "field_name", "")
    if not field_name:
        # Flag may not carry field_name; try to infer from title
        title: str = getattr(flag, "title", "")
        if ":" in title:
            field_name = title.split(":", 1)[-1].strip().lower().replace(" ", "_")

    # Collect relevant fields for this flag's field_name
    relevant = [
        f for f in fields
        if getattr(f, "field_name", "") == field_name
    ]
    if not relevant:
        return []

    suggestions: list[Suggestion] = []
    seen_values: set[str] = set()

    # Build a mapping: doc_type (upper) → list of (value, document_id_str)
    by_source: dict[str, list[tuple[str, str]]] = {}
    for f in relevant:
        doc_id_str = str(getattr(f, "document_id", ""))
        dt = doc_types.get(doc_id_str) or doc_types.get(getattr(f, "document_id", ""))
        if dt is None:
            continue
        dt_upper = dt.upper()
        val = str(getattr(f, "value_normalized", None) or getattr(f, "value_raw", "") or "").strip()
        if val:
            by_source.setdefault(dt_upper, []).append((val, doc_id_str))

    # --- Strategy 1: Source priority ---
    priority_list = SOURCE_PRIORITY.get(field_name, [])
    for src_type in priority_list:
        entries = by_source.get(src_type.upper(), [])
        if entries:
            val, doc_id = entries[0]
            if val not in seen_values:
                seen_values.add(val)
                suggestions.append(Suggestion(
                    field_name=field_name,
                    suggested_value=val,
                    cited_document_ids=[doc_id],
                    rationale=f"Primary source for '{field_name}' is {src_type.replace('_', ' ').title()}.",
                ))
            break  # only the highest-priority source

    # --- Strategy 2: Majority vote ---
    all_values: list[tuple[str, str]] = []
    for entries in by_source.values():
        all_values.extend(entries)

    total = len(all_values)
    if total > 1:
        counts: dict[str, list[str]] = {}
        for val, doc_id in all_values:
            counts.setdefault(val, []).append(doc_id)

        for val, doc_ids in counts.items():
            if len(doc_ids) / total > 0.5 and val not in seen_values:
                seen_values.add(val)
                n = len(doc_ids)
                suggestions.append(Suggestion(
                    field_name=field_name,
                    suggested_value=val,
                    cited_document_ids=doc_ids,
                    rationale=f"Majority of documents ({n}/{total}) show this value.",
                ))

    return suggestions
