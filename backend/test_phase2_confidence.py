"""
Phase 2 — Confidence Framework validation.

Verifies confidence extraction, weighted aggregation, banding, the Confidence
Agent, and (critically) that confidence NEVER changes risk/decision.

Run:  python test_phase2_confidence.py   (or: pytest test_phase2_confidence.py)

Scenario A — strong document + no matches      → High confidence
Scenario B — weak extraction confidence        → Moderate confidence
Scenario C — multiple missing signals          → aggregation still works
Scenario D — legacy case (no confidence fields) → safe defaults
Plus: Confidence Agent does not mutate risk/decision.
"""
from __future__ import annotations

from app.agents.confidence import confidence_agent
from app.models.state import KYCState
from app.services.confidence import (
    build_confidence_summary,
    calculate_overall_confidence,
    confidence_band,
    extract_agent_confidences,
)


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  [ok] {msg}")


def _state(**fields) -> KYCState:
    s = KYCState(case_id="TEST")
    for k, v in fields.items():
        setattr(s, k, v)
    return s


# ── Scenario A — strong document + no matches → High ────────────────────────────
def test_scenario_a_high():
    print("\nScenario A — strong document + clean screening → High confidence")
    s = _state(
        document_verdict={"per_document": [
            {"doc_type_confidence": 0.96, "validity_confidence": 0.96},
        ]},
        entity_resolution={"confidence": 0.92},
        screening_results={"confidence": 0.94},
        evidence_validation={"overall_confidence": 0.92},
        adverse_media={"evidence": []},  # no hits → omitted
    )
    conf = extract_agent_confidences(s)
    overall = calculate_overall_confidence(conf)
    _assert("document_verification" in conf and conf["document_verification"] >= 0.95, "document confidence extracted")
    _assert("adverse_media" not in conf, "adverse media omitted when no hits (not fabricated)")
    _assert(confidence_band(overall) == "High", f"overall {overall} bands as High")
    print("  ->", build_confidence_summary(overall, conf))
    print("  -> Scenario A PASS")


# ── Scenario B — weak extraction → Moderate ─────────────────────────────────────
def test_scenario_b_moderate():
    print("\nScenario B — weak extraction confidence → Moderate confidence")
    s = _state(
        document_verdict={"per_document": []},               # forces fallback
        document_extraction={"overall_confidence": 0.62},    # weak extraction
        entity_resolution={"confidence": 0.78},
        screening_results={"confidence": 0.88},
        evidence_validation={"ml_classification": {"avg_trust_signal": 0.70}},
    )
    conf = extract_agent_confidences(s)
    overall = calculate_overall_confidence(conf)
    _assert(abs(conf["document_verification"] - 0.62) < 1e-6, "falls back to extraction confidence")
    _assert(confidence_band(overall) == "Moderate", f"overall {overall} bands as Moderate")
    print("  -> Scenario B PASS")


# ── Scenario C — multiple missing signals → aggregation still works ─────────────
def test_scenario_c_missing_signals():
    print("\nScenario C — multiple missing confidence signals → aggregation still works")
    s = _state(screening_results={"confidence": 0.94})  # only one signal present
    conf = extract_agent_confidences(s)
    overall = calculate_overall_confidence(conf)
    _assert(len(conf) == 1 and "compliance_screening" in conf, "only present signal extracted")
    _assert(abs(overall - 0.94) < 1e-6, f"single-signal aggregation renormalises ({overall})")
    _assert(calculate_overall_confidence({}) == 0.0, "empty aggregation returns 0.0 (no crash)")
    _assert(build_confidence_summary(0.0, {}).startswith("Verification confidence is low"), "empty summary is safe")
    print("  -> Scenario C PASS")


# ── Scenario D — legacy case → safe defaults ────────────────────────────────────
def test_scenario_d_legacy_defaults():
    print("\nScenario D — legacy case without confidence fields → safe defaults")
    legacy = KYCState.model_validate_json('{"case_id": "LEGACY-1"}')
    _assert(legacy.overall_confidence == 0.0, "overall_confidence defaults to 0.0")
    _assert(legacy.agent_confidences == {}, "agent_confidences defaults to {}")
    _assert(legacy.confidence_summary == "", "confidence_summary defaults to empty")
    # round-trips through dump/validate (what the API/case store do)
    again = KYCState.model_validate(legacy.model_dump())
    _assert(again.overall_confidence == 0.0, "defaults survive dump/validate round-trip")
    print("  -> Scenario D PASS")


# ── Confidence Agent must not affect risk/decision ──────────────────────────────
def test_confidence_agent_does_not_touch_risk():
    print("\nGuard — Confidence Agent leaves risk & decision untouched")
    s = _state(
        document_verdict={"per_document": [{"doc_type_confidence": 0.9, "validity_confidence": 0.9}]},
        entity_resolution={"confidence": 0.9},
        screening_results={"confidence": 0.9},
        risk_assessment={"risk_score": 72, "risk_level": "High", "breakdown": [{"signal": "x", "points": 72}]},
        decision={"status": "ESCALATE", "requires_human_review": True},
    )
    risk_before = dict(s.risk_assessment)
    decision_before = dict(s.decision)
    s = confidence_agent(s)

    _assert(s.risk_assessment == risk_before, "risk_assessment unchanged by Confidence Agent")
    _assert(s.decision == decision_before, "decision unchanged by Confidence Agent")
    _assert(s.overall_confidence > 0, "overall_confidence computed")
    _assert(bool(s.agent_confidences), "agent_confidences populated")
    _assert(bool(s.confidence_summary), "confidence_summary generated")
    _assert("confidence" in s.workflow_path, "confidence step recorded in workflow_path")
    _assert(any(e.agent == "Confidence Agent" for e in s.audit_log), "audit event logged")
    print("  -> Guard PASS")


if __name__ == "__main__":
    test_scenario_a_high()
    test_scenario_b_moderate()
    test_scenario_c_missing_signals()
    test_scenario_d_legacy_defaults()
    test_confidence_agent_does_not_touch_risk()
    print("\nALL PHASE 2 SCENARIOS PASSED")
