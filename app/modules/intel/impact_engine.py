"""
Trade Intelligence — Impact Engine.

Pure Python deterministic impact scoring.
Zero LLM, zero network calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImpactAssessment:
    overall_score: float          # 0.0–1.0
    severity: str                 # low/medium/high/critical
    urgency: str                  # informational/monitor/act_soon/immediate
    affected_industries: list[str]
    affected_countries: list[str]
    supply_chain_risk: str        # none/low/medium/high
    price_effect: str             # positive/negative/neutral/unknown
    rationale: str


def assess_impact(
    enrichment_result: dict,
    org_hs_codes: list[str],
    org_countries: list[str],
    org_industries: list[str],
) -> ImpactAssessment:
    """
    Deterministic impact scoring — no LLM.

    Rules:
    1. Base score = enrichment.impact_score / 5.0
    2. Boost +0.2 if any org HS code matches enrichment.hs_chapters/headings
    3. Boost +0.2 if any org country matches enrichment.affected_countries
    4. Boost +0.1 if any org industry matches enrichment.affected_industries
    5. If event_type='sanctions': severity='critical', urgency='immediate'
    6. If event_type='tariff_change' and org has matching HS: urgency='act_soon'
    7. Cap score at 1.0

    Returns ImpactAssessment with rationale explaining each boost.
    """
    # ------------------------------------------------------------------
    # Normalise inputs
    # ------------------------------------------------------------------
    raw_impact = enrichment_result.get("impact_score", 1)
    try:
        raw_impact = max(1, min(5, int(raw_impact)))
    except (TypeError, ValueError):
        raw_impact = 1

    event_type = (enrichment_result.get("event_type") or "other").lower()
    enrichment_hs_chapters = set(enrichment_result.get("hs_chapters") or [])
    enrichment_hs_headings = set(enrichment_result.get("hs_headings") or [])
    enrichment_countries = set(enrichment_result.get("affected_countries") or [])
    enrichment_industries = set(
        (enrichment_result.get("affected_industries") or []) +
        (enrichment_result.get("industries") or [])
    )
    enrichment_severity = (enrichment_result.get("severity") or "low").lower()
    enrichment_urgency = (enrichment_result.get("urgency") or "informational").lower()
    supply_chain_impact = enrichment_result.get("supply_chain_impact")
    price_effect = (enrichment_result.get("price_effect") or "unknown").lower()

    org_hs_set = set(org_hs_codes or [])
    org_country_set = {c.upper() for c in (org_countries or [])}
    org_industry_set = {i.lower() for i in (org_industries or [])}

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    score = raw_impact / 5.0
    boosts: list[str] = []

    # Boost: HS code match
    hs_match = org_hs_set & (enrichment_hs_chapters | enrichment_hs_headings)
    if hs_match:
        score += 0.2
        boosts.append(f"HS code overlap: {', '.join(sorted(hs_match))}")

    # Boost: country match
    country_match = org_country_set & {c.upper() for c in enrichment_countries}
    if country_match:
        score += 0.2
        boosts.append(f"country overlap: {', '.join(sorted(country_match))}")

    # Boost: industry match
    industry_match = org_industry_set & {i.lower() for i in enrichment_industries}
    if industry_match:
        score += 0.1
        boosts.append(f"industry overlap: {', '.join(sorted(industry_match))}")

    # Cap at 1.0
    score = round(min(score, 1.0), 4)

    # ------------------------------------------------------------------
    # Severity / urgency overrides
    # ------------------------------------------------------------------
    severity = enrichment_severity
    urgency = enrichment_urgency

    if event_type == "sanctions":
        severity = "critical"
        urgency = "immediate"
    elif event_type == "tariff_change" and hs_match:
        if urgency not in ("immediate",):
            urgency = "act_soon"
        if severity not in ("critical", "high"):
            severity = "high"

    # Clamp severity/urgency to valid values
    _valid_severities = {"low", "medium", "high", "critical"}
    _valid_urgencies = {"informational", "monitor", "act_soon", "immediate"}
    if severity not in _valid_severities:
        severity = "low"
    if urgency not in _valid_urgencies:
        urgency = "informational"

    # ------------------------------------------------------------------
    # Supply chain risk
    # ------------------------------------------------------------------
    supply_chain_risk = _compute_supply_chain_risk(score, event_type, bool(hs_match))

    # ------------------------------------------------------------------
    # Rationale
    # ------------------------------------------------------------------
    rationale_parts = [f"Base impact score: {raw_impact}/5 ({score:.2f} overall)."]
    if boosts:
        rationale_parts.append("Relevance boosts: " + "; ".join(boosts) + ".")
    if event_type == "sanctions":
        rationale_parts.append("Sanctions event → severity escalated to critical/immediate.")
    if event_type == "tariff_change" and hs_match:
        rationale_parts.append("Tariff change affects org HS codes → urgency escalated.")
    if not boosts:
        rationale_parts.append("No org-specific overlap found; score reflects global importance only.")

    rationale = " ".join(rationale_parts)

    return ImpactAssessment(
        overall_score=score,
        severity=severity,
        urgency=urgency,
        affected_industries=list(enrichment_industries),
        affected_countries=list(enrichment_countries),
        supply_chain_risk=supply_chain_risk,
        price_effect=price_effect if price_effect in {"positive", "negative", "neutral", "unknown"} else "unknown",
        rationale=rationale,
    )


def _compute_supply_chain_risk(score: float, event_type: str, has_hs_match: bool) -> str:
    """Derive supply chain risk category from score + event type."""
    if event_type == "sanctions":
        return "high"
    if score >= 0.8 or (event_type == "tariff_change" and has_hs_match):
        return "high"
    if score >= 0.6:
        return "medium"
    if score >= 0.3:
        return "low"
    return "none"
