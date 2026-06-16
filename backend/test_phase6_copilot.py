"""
Phase 6 — Compliance Investigation Copilot validation.

Verifies grounded, read-only Q&A: deterministic answers for recognised
questions, a grounded fallback otherwise, "not available" for missing data, and
that the copilot never mutates the case decision/score.

Run:  python test_phase6_copilot.py   (or: pytest test_phase6_copilot.py)

Scenario A — approved customer        → answer uses approval reasons
Scenario B — EDD customer             → lists actual EDD reasons
Scenario C — consistency issues       → lists consistency findings
Scenario D — unsupported question     → routed to grounded LLM fallback
Scenario E — missing data             → "not available in this case"
Plus: copilot is read-only (no decision/score changes).
"""
from __future__ import annotations

from app.agents.copilot import copilot_agent
from app.models.state import KYCState
from app.services.copilot import (
    UNAVAILABLE,
    answer_question,
    build_case_context,
    build_executive_summary,
)


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  [ok] {msg}")


# ── Scenario A — approved → approval reasons ────────────────────────────────────
def test_scenario_a_approved():
    print("\nScenario A — approved customer → uses approval reasons")
    s = KYCState(case_id="A")
    s.customer_profile = {"name": "Emily Chen"}
    s.decision = {"status": "APPROVE", "reasons": ["No sanctions or PEP hits", "All documents verified"]}
    s.risk_assessment = {"risk_score": 12, "risk_level": "Low"}
    res = answer_question(s, "Why was this customer approved?")
    _assert(res["source"] == "deterministic", "answered deterministically")
    _assert("No sanctions or PEP hits" in res["answer"], "answer cites the actual approval reasons")
    print("  -> Scenario A PASS")


# ── Scenario B — EDD → actual EDD reasons ───────────────────────────────────────
def test_scenario_b_edd():
    print("\nScenario B — EDD customer → lists actual EDD reasons")
    s = KYCState(case_id="B")
    s.decision = {"status": "ESCALATE"}
    s.edd_triggered = True
    s.edd_reasons = ["High risk score (82)", "Potential PEP match detected"]
    s.edd_findings = ["Potential PEP association detected (1 watchlist match)."]
    res = answer_question(s, "Why did EDD trigger?")
    _assert(res["source"] == "deterministic", "answered deterministically")
    _assert("Potential PEP match detected" in res["answer"], "answer lists the real EDD reasons")
    _assert("watchlist match" in res["answer"], "answer includes EDD findings")
    print("  -> Scenario B PASS")


# ── Scenario C — consistency issues ─────────────────────────────────────────────
def test_scenario_c_consistency():
    print("\nScenario C — consistency issues → lists findings")
    s = KYCState(case_id="C")
    s.decision = {"status": "REVIEW"}
    s.consistency_score = 0.75
    s.consistency_issues = [
        {"type": "occupation_income_mismatch", "severity": "medium",
         "description": "Student profile reports business revenue."},
    ]
    res = answer_question(s, "What consistency issues exist?")
    _assert(res["source"] == "deterministic", "answered deterministically")
    _assert("Student profile reports business revenue" in res["answer"], "answer lists the real finding")
    print("  -> Scenario C PASS")


# ── Scenario D — unsupported → grounded LLM fallback ────────────────────────────
def test_scenario_d_unsupported():
    print("\nScenario D — unsupported question → grounded LLM fallback")
    s = KYCState(case_id="D")
    s.decision = {"status": "APPROVE"}
    res = answer_question(s, "What is the customer's favourite colour?")
    _assert(res["source"] == "llm", "routed to LLM fallback (not deterministic)")
    _assert(isinstance(res["answer"], str) and len(res["answer"]) > 0, "returns a grounded string answer")
    # Without a Groq key configured, the grounded fallback returns the safe message.
    print(f"  (fallback answer: {res['answer'][:60]}...)")
    print("  -> Scenario D PASS")


# ── Scenario E — missing data ───────────────────────────────────────────────────
def test_scenario_e_missing():
    print("\nScenario E — missing data → 'not available'")
    s = KYCState(case_id="E")
    s.decision = {"status": "APPROVE"}
    res = answer_question(s, "What are the top risk drivers?")  # none recorded
    _assert(res["answer"] == UNAVAILABLE, "returns the 'not available' message for missing data")
    print("  -> Scenario E PASS")


# ── Guard — copilot is read-only ────────────────────────────────────────────────
def test_guard_read_only():
    print("\nGuard — copilot never changes the decision or score")
    s = KYCState(case_id="G")
    s.customer_profile = {"name": "Kim"}
    s.decision = {"status": "ESCALATE", "requires_human_review": True}
    s.risk_assessment = {"risk_score": 82, "risk_level": "High"}
    s.top_risk_drivers = [{"factor": "Sanctions Match", "impact": 50}]
    decision_before, risk_before = dict(s.decision), dict(s.risk_assessment)

    # Asking a question must not mutate the case.
    answer_question(s, "Why was this customer escalated?")
    answer_question(s, "Summarize this case.")
    _assert(s.decision == decision_before, "decision unchanged by Q&A")
    _assert(s.risk_assessment == risk_before, "risk unchanged by Q&A")

    # The copilot agent only adds an executive summary.
    s = copilot_agent(s)
    _assert(s.decision == decision_before, "decision unchanged by copilot agent")
    _assert(bool(s.executive_summary), "executive summary generated")
    _assert("copilot" in s.workflow_path, "copilot step recorded")

    ctx = build_case_context(s)
    _assert(ctx["decision"] == "ESCALATE" and ctx["risk_score"] == 82, "context reflects existing data only")
    _assert(isinstance(build_executive_summary(s), str), "executive summary builds without error")
    print("  -> Guard PASS")


if __name__ == "__main__":
    test_scenario_a_approved()
    test_scenario_b_edd()
    test_scenario_c_consistency()
    test_scenario_d_unsupported()
    test_scenario_e_missing()
    test_guard_read_only()
    print("\nALL PHASE 6 SCENARIOS PASSED")
