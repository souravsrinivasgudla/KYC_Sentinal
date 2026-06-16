"""
Confidence framework (Phase 2).

Aggregates *existing* confidence-like signals already produced by the verification
agents into a single overall confidence score. This answers "how confident is the
system in its conclusion?" and is entirely SEPARATE from risk scoring — it never
influences the APPROVE / REVIEW / ESCALATE decision.

Rules:
  • Reuse existing signals only — never fabricate a confidence value.
  • If an agent exposes no confidence metric, omit it (do not default to a number).
  • All values are normalised to 0–1; the aggregate is clamped to 0–1.
"""

from __future__ import annotations

from typing import Any, Optional

# Weighted aggregation (Part 3). Missing agents are ignored and the present
# weights are renormalised, so the result is always a clean weighted mean.
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "document_verification": 0.30,
    "entity_resolution":     0.20,
    "compliance_screening":  0.20,
    "evidence_validation":   0.15,
    "adverse_media":         0.10,
    "financial_profiling":   0.05,
}

# Friendly labels for the confidence summary text.
AGENT_LABELS: dict[str, str] = {
    "document_verification": "document validation",
    "entity_resolution":     "entity resolution",
    "compliance_screening":  "sanctions screening",
    "evidence_validation":   "evidence validation",
    "adverse_media":         "adverse media analysis",
    "financial_profiling":   "financial profiling",
}

HIGH_THRESHOLD = 0.90
MODERATE_THRESHOLD = 0.70


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _num(value: Any) -> Optional[float]:
    """Return a positive numeric value as float, else None (omit)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


# ── Per-agent extraction from existing state signals ───────────────────────────

def _document_confidence(state) -> Optional[float]:
    """Average of per-document type/validity confidence; fall back to extraction."""
    per_doc = (state.document_verdict or {}).get("per_document") or []
    doc_vals: list[float] = []
    for d in per_doc:
        parts = [_num(d.get("doc_type_confidence")), _num(d.get("validity_confidence"))]
        parts = [p for p in parts if p is not None]
        if parts:
            doc_vals.append(sum(parts) / len(parts))
    if doc_vals:
        return _clamp(sum(doc_vals) / len(doc_vals))

    extraction_conf = _num((state.document_extraction or {}).get("overall_confidence"))
    if extraction_conf is not None:
        return _clamp(extraction_conf)
    return None


def _adverse_media_confidence(state) -> Optional[float]:
    """Reuse semantic similarity / exact-match signals on adverse media hits."""
    evidence = (state.adverse_media or {}).get("evidence") or []
    if not evidence:
        return None
    vals: list[float] = []
    for e in evidence:
        if e.get("match_type") == "exact":
            vals.append(1.0)
        else:
            sim = _num(e.get("similarity"))
            if sim is not None:
                vals.append(sim)
    if not vals:
        return None
    return _clamp(max(vals))


def _evidence_validation_confidence(state) -> Optional[float]:
    ev = state.evidence_validation or {}
    oc = _num(ev.get("overall_confidence"))
    if oc is not None:
        return _clamp(oc)
    ml = ev.get("ml_classification") or {}
    trust = _num(ml.get("avg_trust_signal"))
    if trust is not None:
        return _clamp(trust)
    return None


def extract_agent_confidences(state) -> dict[str, float]:
    """
    Collect the existing confidence signals from each agent. Agents with no
    confidence metric are omitted (never fabricated).
    """
    confidences: dict[str, float] = {}

    doc = _document_confidence(state)
    if doc is not None:
        confidences["document_verification"] = round(doc, 4)

    er = _num((state.entity_resolution or {}).get("confidence"))
    if er is not None:
        confidences["entity_resolution"] = round(_clamp(er), 4)

    sc = _num((state.screening_results or {}).get("confidence"))
    if sc is not None:
        confidences["compliance_screening"] = round(_clamp(sc), 4)

    ev = _evidence_validation_confidence(state)
    if ev is not None:
        confidences["evidence_validation"] = round(ev, 4)

    am = _adverse_media_confidence(state)
    if am is not None:
        confidences["adverse_media"] = round(am, 4)

    # Financial Profiling currently exposes no genuine confidence metric, so it
    # is intentionally omitted (its weight renormalises away).

    return confidences


def calculate_overall_confidence(agent_confidences: dict[str, float]) -> float:
    """Weighted mean over present agents; missing weights renormalise; clamped 0–1."""
    weighted_sum = 0.0
    weight_total = 0.0
    for agent, value in agent_confidences.items():
        weight = CONFIDENCE_WEIGHTS.get(agent, 0.0)
        if weight <= 0 or value is None:
            continue
        weighted_sum += weight * _clamp(value)
        weight_total += weight
    if weight_total == 0:
        return 0.0
    return round(_clamp(weighted_sum / weight_total), 4)


def confidence_band(overall: float) -> str:
    if overall >= HIGH_THRESHOLD:
        return "High"
    if overall >= MODERATE_THRESHOLD:
        return "Moderate"
    return "Low"


def build_confidence_summary(overall: float, agent_confidences: dict[str, float]) -> str:
    """e.g. 'Verification confidence is high (91%). Strong document validation and sanctions screening confidence.'"""
    pct = round(overall * 100)
    band = confidence_band(overall).lower()
    if not agent_confidences:
        return (
            f"Verification confidence is {band} ({pct}%). "
            "No agent confidence signals were available for this case."
        )
    top = sorted(agent_confidences.items(), key=lambda kv: kv[1], reverse=True)[:2]
    strong_labels = [AGENT_LABELS.get(a, a.replace("_", " ")) for a, _ in top]
    if len(strong_labels) == 2:
        strengths = f"{strong_labels[0]} and {strong_labels[1]}"
    else:
        strengths = strong_labels[0]
    qualifier = {
        "high": "Strong",
        "moderate": "Moderate",
        "low": "Limited",
    }[band]
    return (
        f"Verification confidence is {band} ({pct}%). "
        f"{qualifier} {strengths} confidence."
    )
