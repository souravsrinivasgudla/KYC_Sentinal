"""
Phase 4 — Enhanced Due Diligence (EDD) validation.

Verifies the dynamic investigation branch: high-risk profiles trigger EDD and
receive deeper review BEFORE the decision, low-risk profiles skip it, and the
final decision logic is never altered.

Run:  python test_phase4_edd.py   (or: pytest test_phase4_edd.py)

Scenario A — low-risk           → EDD not triggered, EDD agents skipped
Scenario B — risk score >= 70   → EDD triggered, findings generated
Scenario C — document mismatch HIGH → EDD triggered, reason references mismatch
Scenario D — PEP match          → EDD triggered, PEP appears in findings
Scenario E — legacy case        → safe defaults, no errors
Plus: dynamic orchestration (EDD runs only when triggered) + decision untouched.
"""
from __future__ import annotations

from unittest import mock

from app.agents.base import log_event
from app.agents.edd_summary import edd_summary_agent
from app.agents.edd_trigger import edd_trigger_agent
from app.agents.enhanced_due_diligence import enhanced_due_diligence_agent
from app.models.state import CustomerInput, KYCState
from app.orchestrator import graph
from app.services.edd import evaluate_edd_triggers


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  [ok] {msg}")


def _state(**fields) -> KYCState:
    s = KYCState(case_id="TEST")
    for k, v in fields.items():
        setattr(s, k, v)
    return s


# ── Scenario A — low-risk → not triggered ───────────────────────────────────────
def test_scenario_a_low_risk():
    print("\nScenario A — low-risk customer → EDD not triggered")
    s = _state(risk_assessment={"risk_score": 20, "breakdown": []},
               screening_results={"pep": False, "sanctions": False})
    s = edd_trigger_agent(s)
    _assert(s.edd_triggered is False, "EDD not triggered for low risk")
    _assert(s.edd_reasons == [], "no trigger reasons")
    print("  -> Scenario A PASS")


# ── Scenario B — risk >= 70 → triggered + findings ──────────────────────────────
def test_scenario_b_high_score():
    print("\nScenario B — risk score >= 70 → EDD triggered, findings generated")
    s = _state(
        risk_assessment={"risk_score": 78, "breakdown": [
            {"signal": "Elevated Country Risk", "points": 10, "source": "rule"},
        ]},
        screening_results={"pep": False, "sanctions": False},
    )
    s = edd_trigger_agent(s)
    _assert(s.edd_triggered is True, "EDD triggered by high score")
    _assert(any("risk score" in r.lower() for r in s.edd_reasons), "reason references high score")
    s = enhanced_due_diligence_agent(s)
    _assert(len(s.edd_findings) >= 1, "EDD findings generated")
    s = edd_summary_agent(s)
    _assert(bool(s.edd_summary), "EDD summary generated")
    print("  ->", s.edd_summary)
    print("  -> Scenario B PASS")


# ── Scenario C — document mismatch HIGH → triggered, reason references mismatch ──
def test_scenario_c_doc_mismatch():
    print("\nScenario C — HIGH-severity document mismatch → EDD triggered")
    s = _state(
        risk_assessment={"risk_score": 30, "breakdown": []},
        screening_results={},
        document_verdict={"document_type_mismatch": True, "mismatch_severity": "HIGH",
                          "declared_doc_type": "PAN Card", "detected_doc_type": "Aadhaar Card"},
    )
    result = evaluate_edd_triggers(s)
    _assert(result["triggered"] is True, "EDD triggered by document mismatch")
    _assert(any("document type mismatch" in r.lower() for r in result["reasons"]), "reason references mismatch")
    s = edd_trigger_agent(s)
    s = enhanced_due_diligence_agent(s)
    _assert(any("inconsistency" in f.lower() for f in s.edd_findings), "finding references document inconsistency")
    print("  -> Scenario C PASS")


# ── Scenario D — PEP match → triggered, PEP in findings ─────────────────────────
def test_scenario_d_pep():
    print("\nScenario D — PEP match → EDD triggered, PEP in findings")
    s = _state(
        risk_assessment={"risk_score": 40, "breakdown": []},
        screening_results={"pep": True, "pep_hits": [{"matched_name": "X"}], "sanctions": False},
    )
    s = edd_trigger_agent(s)
    _assert(s.edd_triggered is True, "EDD triggered by PEP")
    _assert(any("pep" in r.lower() for r in s.edd_reasons), "reason references PEP")
    s = enhanced_due_diligence_agent(s)
    _assert(any("pep" in f.lower() for f in s.edd_findings), "PEP appears in findings")
    print("  -> Scenario D PASS")


# ── Scenario E — legacy case → safe defaults ────────────────────────────────────
def test_scenario_e_legacy():
    print("\nScenario E — legacy case → safe defaults, no errors")
    legacy = KYCState.model_validate_json('{"case_id": "LEGACY"}')
    _assert(legacy.edd_triggered is False, "edd_triggered defaults to False")
    _assert(legacy.edd_reasons == [] and legacy.edd_findings == [], "lists default to []")
    _assert(legacy.edd_summary == "", "summary defaults to empty")
    # agents run safely on an empty state
    legacy = enhanced_due_diligence_agent(legacy)
    _assert(len(legacy.edd_findings) >= 1, "EDD agent produces a safe fallback finding")
    print("  -> Scenario E PASS")


# ── Guard — EDD agents never change risk/decision ───────────────────────────────
def test_edd_does_not_change_decision():
    print("\nGuard — EDD agents leave risk score & decision untouched")
    s = _state(
        risk_assessment={"risk_score": 80, "risk_level": "High", "breakdown": []},
        decision={"status": "ESCALATE", "requires_human_review": True},
        screening_results={"pep": True, "pep_hits": [{}]},
    )
    risk_before, decision_before = dict(s.risk_assessment), dict(s.decision)
    s = edd_trigger_agent(s)
    s = enhanced_due_diligence_agent(s)
    s = edd_summary_agent(s)
    _assert(s.risk_assessment == risk_before, "risk_assessment unchanged")
    _assert(s.decision == decision_before, "decision unchanged")
    print("  -> Guard PASS")


# ── Dynamic orchestration — EDD runs only when triggered ────────────────────────
CUSTOMER = CustomerInput(name="T", dob="1990-01-01", nationality="IN", occupation="x",
                         document_type="PAN Card", id_number="ABCDE1234F")


def _orchestration_patches(risk_score: int):
    def passthrough(wf, name):
        def fn(s, *a, **k):
            s.workflow_path.append(wf)
            log_event(s, name, "fake", {})
            return s
        return fn

    def fake_risk(s):
        s.risk_assessment = {"risk_score": risk_score, "risk_level": "High" if risk_score >= 70 else "Low", "breakdown": []}
        s.workflow_path.append("risk_scoring")
        log_event(s, "Risk Scoring Agent", "fake", {})
        return s

    def fake_doc(s):
        s.document_verdict = {"verdict": "VERIFIED", "pipeline_blocked": False, "per_document": []}
        s.workflow_path.append("indian_document_verification")
        log_event(s, "Indian Document Verification Agent", "fake", {})
        return s

    return {
        "intake_agent": lambda s, c: passthrough("intake", "Customer Intake Agent")(s),
        "document_extraction_agent": passthrough("document_extraction", "Document Extraction Agent"),
        "groq_verification_agent": passthrough("groq_verification", "Groq Verification Agent"),
        "normalization_agent": passthrough("normalization", "Profile Normalization Agent"),
        "indian_document_verification_agent": fake_doc,
        "entity_resolution_agent": passthrough("entity_resolution", "Entity Resolution Agent"),
        "compliance_screening_agent": passthrough("compliance_screening", "Compliance Screening Agent"),
        "adverse_media_agent": passthrough("adverse_media", "Adverse Media Agent"),
        "evidence_validation_agent": passthrough("evidence_validation", "Evidence Validation Agent"),
        "financial_profiling_agent": passthrough("financial_profiling", "Financial Profiling Agent"),
        "confidence_agent": passthrough("confidence", "Confidence Agent"),
        "risk_scoring_agent": fake_risk,
        "risk_breakdown_agent": passthrough("risk_breakdown", "Risk Breakdown Agent"),
        "explainability_agent": passthrough("explainability", "Explainability Agent"),
        "decision_agent": lambda s: (s.decision.update({"status": "ESCALATE" if risk_score >= 70 else "APPROVE", "requires_human_review": False}) or s),
        "human_review_agent": passthrough("human_review", "Human Review Agent"),
        "audit_report_agent": lambda s: s,
    }


def _run(risk_score: int):
    events, final = [], None
    with mock.patch.multiple(graph, **_orchestration_patches(risk_score)):
        for ev in graph.orchestrator.run_with_events(CUSTOMER):
            events.append(ev)
            if ev.get("type") == "complete":
                final = KYCState.model_validate(ev["state"])
    return events, final


def test_dynamic_orchestration():
    print("\nDynamic orchestration — EDD branch alters execution by risk")
    # High risk → EDD agents execute
    events, final = _run(85)
    _assert(final.edd_triggered is True, "high-risk: EDD triggered")
    _assert("enhanced_due_diligence" in final.workflow_path, "high-risk: EDD agent executed")
    _assert("edd_summary" in final.workflow_path, "high-risk: EDD summary executed")
    notes = [e for e in events if e.get("step_id", "").startswith("orchestrator_edd")]
    _assert(any("Enhanced Due Diligence required" in e["message"] for e in notes), "launch note emitted")

    # Low risk → EDD agents skipped
    events2, final2 = _run(20)
    _assert(final2.edd_triggered is False, "low-risk: EDD not triggered")
    _assert("enhanced_due_diligence" not in final2.workflow_path, "low-risk: EDD agent did NOT run")
    step_events = [e for e in events2 if e.get("type") == "step"]
    skipped = {e["step_id"] for e in step_events if e["status"] == "skipped"}
    _assert("enhanced_due_diligence" in skipped and "edd_summary" in skipped, "low-risk: EDD agents emitted as skipped")
    _assert(any("EDD not required" in e.get("message", "") for e in step_events), "low-risk: 'EDD not required' note emitted")
    print("  -> Dynamic orchestration PASS")


if __name__ == "__main__":
    test_scenario_a_low_risk()
    test_scenario_b_high_score()
    test_scenario_c_doc_mismatch()
    test_scenario_d_pep()
    test_scenario_e_legacy()
    test_edd_does_not_change_decision()
    test_dynamic_orchestration()
    print("\nALL PHASE 4 SCENARIOS PASSED")
