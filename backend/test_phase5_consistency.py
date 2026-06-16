"""
Phase 5 — Consistency Agent validation.

Verifies cross-signal contradiction detection, the consistency score, and that
the agent is read-only (never changes risk, confidence, EDD, or the decision).

Run:  python test_phase5_consistency.py   (or: pytest test_phase5_consistency.py)

Scenario A — normal customer            → no issues, score ~1.0
Scenario B — student + business revenue → occupation_income_mismatch
Scenario C — young + retired            → age_occupation_mismatch
Scenario D — missing funds + high risk  → critical_information_gap
Scenario E — legacy case                → safe defaults, no errors
Plus: agent leaves decision untouched; dynamic orchestration (runs / skips).
"""
from __future__ import annotations

from unittest import mock

from app.agents.base import log_event
from app.agents.consistency import consistency_agent
from app.models.state import CustomerInput, KYCState
from app.orchestrator import graph
from app.services.consistency import (
    calculate_consistency_score,
    detect_consistency_issues,
)


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  [ok] {msg}")


def _state(profile: dict, risk_score: int = 20, edd: bool = False, document_verdict: dict | None = None) -> KYCState:
    s = KYCState(case_id="TEST")
    s.customer_profile = profile
    s.risk_assessment = {"risk_score": risk_score, "breakdown": []}
    s.edd_triggered = edd
    if document_verdict:
        s.document_verdict = document_verdict
    return s


def _types(issues):
    return [i["type"] for i in issues]


# ── Scenario A — normal → no issues ─────────────────────────────────────────────
def test_scenario_a_normal():
    print("\nScenario A — normal customer → no issues, score ~1.0")
    s = _state({"occupation": "Engineer", "source_of_funds": "Salary",
                "dob": "1988-04-12", "nationality": "India", "id_number": "ABCDE1234F"})
    issues = detect_consistency_issues(s)
    _assert(issues == [], "no consistency issues")
    _assert(calculate_consistency_score(issues) == 1.0, "score is 1.0")
    print("  -> Scenario A PASS")


# ── Scenario B — student + business revenue ─────────────────────────────────────
def test_scenario_b_student_business():
    print("\nScenario B — student + business revenue → occupation_income_mismatch")
    s = _state({"occupation": "Student", "source_of_funds": "Business Revenue",
                "dob": "2003-01-01", "id_number": "X"})
    issues = detect_consistency_issues(s)
    _assert("occupation_income_mismatch" in _types(issues), "occupation_income_mismatch detected")
    _assert(calculate_consistency_score(issues) == 0.75, "single medium issue → 0.75")
    print("  -> Scenario B PASS")


# ── Scenario C — young + retired ────────────────────────────────────────────────
def test_scenario_c_age_occupation():
    print("\nScenario C — young customer + retired → age_occupation_mismatch")
    s = _state({"occupation": "Retired", "source_of_funds": "Savings",
                "dob": "2008-01-01", "id_number": "X"})
    issues = detect_consistency_issues(s)
    _assert("age_occupation_mismatch" in _types(issues), "age_occupation_mismatch detected")
    print("  -> Scenario C PASS")


# ── Scenario D — missing funds + high risk ──────────────────────────────────────
def test_scenario_d_critical_gap():
    print("\nScenario D — missing source of funds + high risk → critical_information_gap")
    s = _state({"occupation": "Consultant", "source_of_funds": "",
                "dob": "1980-01-01", "id_number": "X"}, risk_score=78)
    issues = detect_consistency_issues(s)
    _assert("critical_information_gap" in _types(issues), "critical_information_gap detected")
    # Same profile but low risk → no gap flagged
    s_low = _state({"occupation": "Consultant", "source_of_funds": "",
                    "dob": "1980-01-01", "id_number": "X"}, risk_score=20)
    _assert("critical_information_gap" not in _types(detect_consistency_issues(s_low)),
            "no gap flagged for low-risk profile (conservative)")
    print("  -> Scenario D PASS")


# ── Scenario E — legacy → safe defaults ─────────────────────────────────────────
def test_scenario_e_legacy():
    print("\nScenario E — legacy case → safe defaults, no errors")
    legacy = KYCState.model_validate_json('{"case_id": "LEGACY"}')
    _assert(legacy.consistency_issues == [], "consistency_issues defaults to []")
    _assert(legacy.consistency_score == 1.0, "consistency_score defaults to 1.0")
    _assert(legacy.consistency_summary == "", "consistency_summary defaults to empty")
    legacy = consistency_agent(legacy)  # runs safely on an empty profile
    _assert(legacy.consistency_score == 1.0, "agent runs safely on empty state")
    print("  -> Scenario E PASS")


# ── Guard — agent does not change risk/decision ─────────────────────────────────
def test_guard_no_decision_change():
    print("\nGuard — Consistency Agent leaves risk & decision untouched")
    s = _state({"occupation": "Student", "source_of_funds": "Business Revenue",
                "dob": "2003-01-01", "id_number": "X"}, risk_score=72)
    s.decision = {"status": "ESCALATE", "requires_human_review": True}
    risk_before, decision_before = dict(s.risk_assessment), dict(s.decision)
    s = consistency_agent(s)
    _assert(s.risk_assessment == risk_before, "risk_assessment unchanged")
    _assert(s.decision == decision_before, "decision unchanged")
    _assert(len(s.consistency_issues) >= 1, "issues recorded")
    _assert("consistency" in s.workflow_path, "step recorded in workflow_path")
    print("  -> Guard PASS")


# ── Dynamic orchestration — runs for non-rejected, skipped for rejected ─────────
CUSTOMER = CustomerInput(name="T", dob="2003-01-01", nationality="IN", occupation="Student",
                         source_of_funds="Business Revenue", document_type="PAN Card", id_number="ABCDE1234F")


def _patches(doc_blocked: bool):
    def pt(wf, name):
        def fn(s, *a, **k):
            s.workflow_path.append(wf); log_event(s, name, "fake", {}); return s
        return fn

    def fake_doc(s):
        s.document_verdict = {"verdict": "REJECTED" if doc_blocked else "VERIFIED",
                              "pipeline_blocked": doc_blocked, "rejection_reasons": ["x"] if doc_blocked else [],
                              "per_document": []}
        s.workflow_path.append("indian_document_verification"); log_event(s, "Indian Document Verification Agent", "f", {}); return s

    return {
        "intake_agent": lambda s, c: (s.customer_profile.update({"occupation": "Student", "source_of_funds": "Business Revenue", "dob": "2003-01-01"}) or pt("intake", "Customer Intake Agent")(s)),
        "document_extraction_agent": pt("document_extraction", "Document Extraction Agent"),
        "groq_verification_agent": pt("groq_verification", "Groq Verification Agent"),
        "normalization_agent": pt("normalization", "Profile Normalization Agent"),
        "indian_document_verification_agent": fake_doc,
        "entity_resolution_agent": pt("entity_resolution", "Entity Resolution Agent"),
        "compliance_screening_agent": pt("compliance_screening", "Compliance Screening Agent"),
        "adverse_media_agent": pt("adverse_media", "Adverse Media Agent"),
        "evidence_validation_agent": pt("evidence_validation", "Evidence Validation Agent"),
        "financial_profiling_agent": pt("financial_profiling", "Financial Profiling Agent"),
        "confidence_agent": pt("confidence", "Confidence Agent"),
        "risk_scoring_agent": lambda s: (s.risk_assessment.update({"risk_score": 30, "breakdown": []}) or s.workflow_path.append("risk_scoring") or s),
        "risk_breakdown_agent": pt("risk_breakdown", "Risk Breakdown Agent"),
        "explainability_agent": pt("explainability", "Explainability Agent"),
        "decision_agent": lambda s: (s.decision.update({"status": "APPROVE", "requires_human_review": False}) or s),
        "human_review_agent": pt("human_review", "Human Review Agent"),
        "audit_report_agent": lambda s: s,
    }


def _run(doc_blocked: bool):
    events, final = [], None
    with mock.patch.multiple(graph, **_patches(doc_blocked)):
        for ev in graph.orchestrator.run_with_events(CUSTOMER):
            events.append(ev)
            if ev.get("type") == "complete":
                final = KYCState.model_validate(ev["state"])
    return events, final


def test_dynamic_orchestration():
    print("\nDynamic orchestration — Consistency runs (normal) / skipped (rejected)")
    events, final = _run(doc_blocked=False)
    _assert("consistency" in final.workflow_path, "non-rejected: Consistency Agent executed")
    _assert(len(final.consistency_issues) >= 1, "non-rejected: issues detected end-to-end")

    events2, final2 = _run(doc_blocked=True)
    _assert("consistency" not in final2.workflow_path, "rejected: Consistency Agent did NOT run")
    step_events = [e for e in events2 if e.get("type") == "step"]
    skipped = {e["step_id"] for e in step_events if e["status"] == "skipped"}
    _assert("consistency" in skipped, "rejected: Consistency Agent emitted as skipped")
    print("  -> Dynamic orchestration PASS")


if __name__ == "__main__":
    test_scenario_a_normal()
    test_scenario_b_student_business()
    test_scenario_c_age_occupation()
    test_scenario_d_critical_gap()
    test_scenario_e_legacy()
    test_guard_no_decision_change()
    test_dynamic_orchestration()
    print("\nALL PHASE 5 SCENARIOS PASSED")
