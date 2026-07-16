"""
Pure normalization functions for extracted field values.
No I/O, no database access.
Returns normalized string or None.
"""
from decimal import Decimal, InvalidOperation


def normalize_decimal(value_raw: str) -> str | None:
    """Strip commas, currency symbols, whitespace; return canonical Decimal string."""
    cleaned = value_raw.strip()
    # Remove currency symbols
    for sym in ("$", "£", "€", "¥", "₹", "₩", "₪", "₫", "฿"):
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.replace(",", "").strip()
    try:
        return str(Decimal(cleaned))
    except InvalidOperation:
        return None


def normalize_date(value_raw: str) -> str | None:
    """Return ISO 8601 YYYY-MM-DD or None."""
    from datetime import datetime as _dt
    from app.modules.field_extraction.validators import _DATE_FORMATS
    cleaned = value_raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = _dt.strptime(cleaned, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_currency(value_raw: str) -> str | None:
    """Return uppercase ISO code or None."""
    from app.modules.field_extraction.validators import _ISO_4217
    cleaned = value_raw.strip().upper()
    if cleaned in _ISO_4217:
        return cleaned
    return None


def normalize_incoterm(value_raw: str) -> str | None:
    """Return uppercase canonical Incoterm token or None."""
    from app.modules.field_extraction.validators import _INCOTERMS_2020
    token = value_raw.strip().upper().split()[0] if value_raw.strip() else ""
    if token in _INCOTERMS_2020:
        return token
    return None


def normalize_eori(value_raw: str) -> str | None:
    """Uppercase and strip spaces from an EORI number."""
    import re
    cleaned = re.sub(r"\s+", "", value_raw.strip().upper())
    # Basic pattern: 2-letter country code + up to 15 alphanumerics
    if re.match(r"^[A-Z]{2}[A-Z0-9]{1,15}$", cleaned):
        return cleaned
    return cleaned or None


def normalize_field(field_name: str, value_raw: str) -> str | None:
    """Dispatch to correct normalizer based on field_name."""
    from app.modules.field_extraction.schemas import FieldName
    try:
        fn = FieldName(field_name)
    except ValueError:
        return None

    _DECIMAL_FIELDS = {
        FieldName.INVOICE_VALUE,
        FieldName.VAT_VALUE,
        FieldName.FREIGHT_VALUE,
        FieldName.INSURANCE_VALUE,
        FieldName.GROSS_WEIGHT,
        FieldName.NET_WEIGHT,
        FieldName.QUANTITY,
        FieldName.TOTAL_PACKAGES,
    }
    _DATE_FIELDS = {
        FieldName.INVOICE_DATE,
        FieldName.DUE_DATE,
        FieldName.SHIPMENT_DATE,
        FieldName.EXPIRY_DATE,
    }

    if fn in _DECIMAL_FIELDS:
        return normalize_decimal(value_raw)
    elif fn in _DATE_FIELDS:
        return normalize_date(value_raw)
    elif fn == FieldName.CURRENCY:
        return normalize_currency(value_raw)
    elif fn == FieldName.INCOTERM:
        return normalize_incoterm(value_raw)
    elif fn == FieldName.EORI_NUMBER:
        return normalize_eori(value_raw)
    return None
