"""
Mismatch detection engine.
CRITICAL: PURE PYTHON — ZERO LLM CALLS, ZERO I/O, ZERO NETWORK IMPORTS.
Takes extracted fields + settings, returns list of FlagSpec dataclasses.
No DB access.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


LOW_CONFIDENCE_THRESHOLD = 0.70

# Field names as string literals to avoid import cycles with schemas
_ZERO_TOLERANCE_FIELDS = {"hs_code", "stated_origin", "currency"}
_PCT_BAND_FIELDS = {"invoice_value", "gross_weight", "net_weight", "quantity"}
_FUZZY_NAME_FIELDS = {"party_shipper", "party_consignee"}


@dataclass
class FlagSpec:
    flag_type: str   # mismatch / low_confidence / missing_field
    severity: str    # critical / warning / info
    title: str
    description: str
    conflicting_values: list[dict] = field(default_factory=list)


def _to_decimal(value_raw: str) -> Decimal | None:
    try:
        cleaned = value_raw.strip().replace(",", "")
        for sym in ("$", "£", "€", "¥", "₹"):
            cleaned = cleaned.replace(sym, "")
        return Decimal(cleaned.strip())
    except (InvalidOperation, AttributeError):
        return None


def compare_shipment_fields(fields: list, settings) -> list[FlagSpec]:
    """
    Group fields by field_name and apply comparison rules.

    Parameters
    ----------
    fields   : list of ExtractedField ORM objects (or any object with attributes:
               field_name, value_raw, value_normalized, confidence, document_id, page_number)
    settings : object with weight_qty_tolerance_pct, value_tolerance_pct, name_match_threshold
               (or None — defaults will be used)

    Returns
    -------
    list[FlagSpec]
    """
    # Default tolerances
    weight_qty_tol = float(getattr(settings, "weight_qty_tolerance_pct", 0.5)) / 100.0
    value_tol = float(getattr(settings, "value_tolerance_pct", 1.0)) / 100.0
    name_threshold = float(getattr(settings, "name_match_threshold", 0.93))

    flag_specs: list[FlagSpec] = []

    # Group by field_name
    by_name: dict[str, list] = {}
    for f in fields:
        by_name.setdefault(f.field_name, []).append(f)

    for fname, group in by_name.items():
        # ── Low confidence flags (per-field, info) ──────────────────────────
        for f in group:
            if f.confidence < LOW_CONFIDENCE_THRESHOLD:
                flag_specs.append(FlagSpec(
                    flag_type="low_confidence",
                    severity="info",
                    title=f"Low confidence: {fname}",
                    description=(
                        f"Field '{fname}' extracted with confidence {f.confidence:.0%}, "
                        f"below the {LOW_CONFIDENCE_THRESHOLD:.0%} threshold."
                    ),
                    conflicting_values=[{
                        "document_id": str(f.document_id),
                        "field_name": fname,
                        "value_raw": f.value_raw,
                        "page_number": f.page_number,
                        "confidence": f.confidence,
                    }],
                ))

        # Need at least 2 values to compare
        if len(group) < 2:
            continue

        # Only compare fields with sufficient confidence; mark others as unverified
        confident = [f for f in group if f.confidence >= LOW_CONFIDENCE_THRESHOLD]
        if len(confident) < 2:
            continue

        # ── Zero-tolerance fields (critical) ────────────────────────────────
        if fname in _ZERO_TOLERANCE_FIELDS:
            values = {(f.value_normalized or f.value_raw).strip().upper() for f in confident}
            if len(values) > 1:
                flag_specs.append(FlagSpec(
                    flag_type="mismatch",
                    severity="critical",
                    title=f"Mismatch: {fname}",
                    description=(
                        f"Field '{fname}' has conflicting values across documents: "
                        + ", ".join(sorted(values))
                    ),
                    conflicting_values=[
                        {
                            "document_id": str(f.document_id),
                            "field_name": fname,
                            "value_raw": f.value_raw,
                            "page_number": f.page_number,
                        }
                        for f in confident
                    ],
                ))

        # ── Percentage-band fields (warning) ────────────────────────────────
        elif fname in _PCT_BAND_FIELDS:
            tolerance = weight_qty_tol if fname in {"gross_weight", "net_weight", "quantity"} else value_tol
            decimals = []
            for f in confident:
                raw = f.value_normalized or f.value_raw
                d = _to_decimal(raw)
                if d is not None:
                    decimals.append((f, d))

            if len(decimals) >= 2:
                min_val = min(d for _, d in decimals)
                max_val = max(d for _, d in decimals)
                if max_val > 0:
                    spread = (max_val - min_val) / max_val
                    if spread > Decimal(str(tolerance)):
                        flag_specs.append(FlagSpec(
                            flag_type="mismatch",
                            severity="warning",
                            title=f"Value mismatch: {fname}",
                            description=(
                                f"Field '{fname}' varies by {float(spread):.1%} across documents "
                                f"(tolerance: {tolerance:.1%})."
                            ),
                            conflicting_values=[
                                {
                                    "document_id": str(f.document_id),
                                    "field_name": fname,
                                    "value_raw": f.value_raw,
                                    "page_number": f.page_number,
                                }
                                for f, _ in decimals
                            ],
                        ))

        # ── Fuzzy name fields (warning) ──────────────────────────────────────
        elif fname in _FUZZY_NAME_FIELDS:
            from app.modules.mismatch.fuzzy import names_match
            # Compare all pairs
            mismatched_pairs = []
            for i in range(len(confident)):
                for j in range(i + 1, len(confident)):
                    a, b = confident[i], confident[j]
                    if not names_match(a.value_raw, b.value_raw, name_threshold):
                        mismatched_pairs.append((a, b))

            if mismatched_pairs:
                all_fields = {f for pair in mismatched_pairs for f in pair}
                flag_specs.append(FlagSpec(
                    flag_type="mismatch",
                    severity="warning",
                    title=f"Name mismatch: {fname}",
                    description=(
                        f"Party name '{fname}' does not match across documents "
                        f"(threshold: {name_threshold:.0%})."
                    ),
                    conflicting_values=[
                        {
                            "document_id": str(f.document_id),
                            "field_name": fname,
                            "value_raw": f.value_raw,
                            "page_number": f.page_number,
                        }
                        for f in all_fields
                    ],
                ))

    return flag_specs
