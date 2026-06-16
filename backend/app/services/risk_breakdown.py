"""
Risk contribution breakdown (Phase 3).

Decomposes the final risk score into per-factor contributions for transparency
and audit. This is EXPLAINABILITY ONLY — it reads the contributions that
risk_scoring already recorded in `risk_assessment.breakdown` and never alters
the score, weights, or decision.

Each rule-based signal in the breakdown is an actual score contribution. The
XGBoost blend entry (source == "ml") is excluded here because it is a blended
model prediction, not a discrete additive factor — it remains visible in the
existing ML prediction badge.
"""

from __future__ import annotations

from typing import Any

# (keyword substrings, category) — first match wins. Keywords are lower-cased.
_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("sanctions",), "sanctions"),
    (("pep",), "pep"),
    (("adverse media", "negative news"), "adverse_media"),
    (("source of funds", "funds"), "funds"),
    (("occupation",), "occupation"),
    (("country",), "country"),
    (("id number", "id mismatch", "identity"), "identity"),
    (("document type",), "document"),
    (("document", "proof", "evidence"), "document"),
    (("groq", "ai risk"), "ai"),
    (("missing",), "missing_info"),
]


def _categorize(signal: str) -> str:
    s = (signal or "").lower()
    for keywords, category in _CATEGORY_RULES:
        if any(k in s for k in keywords):
            return category
    return "other"


def generate_risk_breakdown(breakdown: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalize the risk_scoring breakdown into UI-friendly contributions,
    sorted by absolute impact descending. Excludes the ML blend entry and
    zero-impact rows. Never fabricates values.
    """
    contributions: list[dict[str, Any]] = []
    for entry in breakdown or []:
        if entry.get("source") == "ml":
            continue
        impact = entry.get("points", 0)
        if not isinstance(impact, (int, float)) or impact == 0:
            continue
        contributions.append({
            "factor": entry.get("signal", "Unknown Factor"),
            "impact": impact,
            "category": _categorize(entry.get("signal", "")),
        })
    contributions.sort(key=lambda c: abs(c["impact"]), reverse=True)
    return contributions


def calculate_total_contribution(contributions: list[dict[str, Any]]) -> float:
    """Sum of all contribution impacts (explains the rule-based portion of the score)."""
    return sum(c.get("impact", 0) for c in contributions)


def top_risk_drivers(contributions: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """The N highest-impact contributors (already sorted)."""
    return contributions[:limit]


def _fmt(impact: float) -> str:
    return f"+{impact}" if impact >= 0 else str(impact)


def build_breakdown_summary(contributions: list[dict[str, Any]]) -> str:
    """e.g. 'The largest contributors were Document Type Inconsistency (+25) and High Risk Country (+15).'"""
    if not contributions:
        return "No discrete risk factors contributed to this score."
    top = contributions[:2]
    parts = [f"{c['factor']} ({_fmt(c['impact'])})" for c in top]
    if len(parts) == 2:
        drivers = f"{parts[0]} and {parts[1]}"
    else:
        drivers = parts[0]
    return f"The largest contributors were {drivers}."
