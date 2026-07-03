"""
Pure validation functions for extracted field values.
No I/O, no database access.
Returns (is_valid: bool, reason: str).
"""
from decimal import Decimal, InvalidOperation

# ISO 4217 common currency codes (subset covering >99% of trade documents)
_ISO_4217 = {
    "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CLP", "CNY",
    "COP", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP",
    "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD",
    "GNF", "GTQ", "GYD", "HKD", "HNL", "HRK", "HTG", "HUF", "IDR", "ILS",
    "INR", "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR",
    "KMF", "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD",
    "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU",
    "MUR", "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK",
    "NPR", "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG",
    "QAR", "RON", "RSD", "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK",
    "SGD", "SHP", "SLL", "SOS", "SRD", "STN", "SVC", "SYP", "SZL", "THB",
    "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX",
    "USD", "UYU", "UZS", "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF",
    "XPF", "YER", "ZAR", "ZMW", "ZWL",
}

# Incoterms 2020
_INCOTERMS_2020 = {
    "EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP",
    "FAS", "FOB", "CFR", "CIF",
}

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y/%m/%d",
    "%d.%m.%Y",
]


def validate_currency(value: str) -> tuple[bool, str]:
    cleaned = value.strip().upper()
    if cleaned in _ISO_4217:
        return True, ""
    return False, f"'{value}' is not a recognised ISO 4217 currency code"


def validate_incoterm(value: str) -> tuple[bool, str]:
    # Strip optional place-of-delivery suffix, e.g. "FOB Shanghai" → "FOB"
    token = value.strip().upper().split()[0] if value.strip() else ""
    if token in _INCOTERMS_2020:
        return True, ""
    return False, f"'{value}' is not a recognised Incoterms 2020 term"


def validate_date(value: str) -> tuple[bool, str]:
    from datetime import datetime as _dt
    cleaned = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            _dt.strptime(cleaned, fmt)
            return True, ""
        except ValueError:
            continue
    return False, f"'{value}' does not match any recognised date format"


def validate_decimal(value: str) -> tuple[bool, str]:
    # Strip common noise before attempting parse
    cleaned = value.strip().replace(",", "").lstrip("$£€¥₹").strip()
    try:
        Decimal(cleaned)
        return True, ""
    except InvalidOperation:
        return False, f"'{value}' cannot be parsed as a decimal number"


def validate_weight_sanity(net: str, gross: str) -> tuple[bool, str]:
    try:
        net_val = Decimal(net.strip().replace(",", ""))
        gross_val = Decimal(gross.strip().replace(",", ""))
    except InvalidOperation:
        return False, "Net or gross weight is not a valid decimal"
    if net_val <= gross_val:
        return True, ""
    return False, f"Net weight ({net_val}) exceeds gross weight ({gross_val})"


def get_validator(field_name: str):
    """Return the appropriate (value: str) -> (bool, str) validator for the field."""
    from app.modules.field_extraction.schemas import FieldName
    _MAP = {
        FieldName.CURRENCY: validate_currency,
        FieldName.INCOTERM: validate_incoterm,
        FieldName.INVOICE_DATE: validate_date,
        FieldName.SHIPMENT_DATE: validate_date,
        FieldName.INVOICE_VALUE: validate_decimal,
        FieldName.GROSS_WEIGHT: validate_decimal,
        FieldName.NET_WEIGHT: validate_decimal,
        FieldName.QUANTITY: validate_decimal,
    }
    try:
        from app.modules.field_extraction.schemas import FieldName as FN
        key = FN(field_name)
        return _MAP.get(key)
    except ValueError:
        return None
