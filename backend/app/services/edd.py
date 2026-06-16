"""
Enhanced Due Diligence (EDD) trigger evaluation (Phase 4).

Decides whether a high-risk profile should receive a deeper investigation pass
BEFORE the final decision. Triggers use only signals already produced by the
upstream agents — no new risk signals are invented, and the risk score and
decision thresholds are never modified.
"""

from __future__ import annotations

from typing import Any

EDD_RISK_THRESHOLD = 70
HIGH_FACTOR_POINTS = 20      # a single contribution this large is "high-risk"
MULTI_FACTOR_COUNT = 2       # this many high factors at once → EDD


def evaluate_edd_triggers(state) -> dict[str, Any]:
    """
    Return {"triggered": bool, "reasons": [str, ...]} based on existing outputs:
      • risk score >= 70
      • PEP match detected
      • sanctions match detected
      • HIGH-severity document type mismatch
      • multiple simultaneous high-risk factors
    """
    reasons: list[str] = []

    risk_score = state.risk_assessment.get("risk_score", 0) or 0
    if risk_score >= EDD_RISK_THRESHOLD:
        reasons.append(f"High risk score ({risk_score})")

    screening = state.screening_results or {}
    if screening.get("pep"):
        reasons.append("Potential PEP match detected")
    if screening.get("sanctions"):
        reasons.append("Sanctions match detected")

    dv = state.document_verdict or {}
    if dv.get("document_type_mismatch") and dv.get("mismatch_severity") == "HIGH":
        reasons.append("High-severity document type mismatch")

    # Multiple high-risk rule factors present simultaneously (exclude ML blend).
    breakdown = state.risk_assessment.get("breakdown", []) or []
    high_factors = [
        b for b in breakdown
        if b.get("source") != "ml" and (b.get("points", 0) or 0) >= HIGH_FACTOR_POINTS
    ]
    if len(high_factors) >= MULTI_FACTOR_COUNT:
        reasons.append(f"Multiple high-risk factors present ({len(high_factors)})")

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique_reasons = [r for r in reasons if not (r in seen or seen.add(r))]

    return {"triggered": len(unique_reasons) > 0, "reasons": unique_reasons}
