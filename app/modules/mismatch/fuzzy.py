"""
Fuzzy name matching for party name comparison.
PURE PYTHON — no LLM, no network, no I/O.
"""
import re

from rapidfuzz import fuzz

_SUFFIX_PATTERN = re.compile(
    r"\b(ltd|limited|gmbh|sa|bv|srl|llc|inc|corp|co|pty|plc)\b",
    re.IGNORECASE,
)


def normalize_party_name(name: str) -> str:
    """Lowercase, strip legal suffixes, normalise whitespace."""
    lowered = name.lower()
    stripped = _SUFFIX_PATTERN.sub("", lowered)
    return " ".join(stripped.split())


def names_match(a: str, b: str, threshold: float) -> bool:
    """Return True if the fuzzy token-sort ratio meets or exceeds threshold (0-1 scale)."""
    score = fuzz.token_sort_ratio(normalize_party_name(a), normalize_party_name(b)) / 100.0
    return score >= threshold
