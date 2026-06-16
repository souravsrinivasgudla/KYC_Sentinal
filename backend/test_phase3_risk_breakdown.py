"""
Phase 3 — Risk Contribution Breakdown validation.

Verifies decomposition, sorting, top-driver selection, and (critically) that the
breakdown is purely explanatory and never changes the risk score or decision.

Run:  python test_phase3_risk_breakdown.py   (or: pytest test_phase3_risk_breakdown.py)

Scenario A — low-risk customer        → few small contributors
Scenario B — document mismatch        → Document Type Inconsistency near the top
Scenario C — high-risk country + PEP  → both visible in Top Risk Drivers
Scenario D — legacy case              → missing contributions handled gracefully
Plus: Risk Breakdown Agent leaves the risk score & decision untouched.
"""
from __future__ import annotations

from app.agents.risk_breakdown import risk_breakdown_agent
from app.models.state import KYCState
from app.services.risk_breakdown import (
    calculate_total_contribution,
    generate_risk_breakdown,
    top_risk_drivers,
)


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  [ok] {msg}")


def _state_with_breakdown(breakdown, risk_score=0):
    s = KYCState(case_id="TEST")
    s.risk_assessment = {"risk_score": risk_score, "risk_level": "Low", "breakdown": breakdown}
    return s


# ── Scenario A — low-risk → few small contributors ──────────────────────────────
def test_scenario_a_low_risk():
    print("\nScenario A — low-risk customer → few small contributors")
    bd = [{"signal": "Elevated Country Risk", "points": 10, "source": "rule"}]
    contribs = generate_risk_breakdown(bd)
    _assert(len(contribs) == 1, "only one small contributor")
    _assert(contribs[0]["impact"] == 10, "impact preserved (10)")
    _assert(calculate_total_contribution(contribs) == 10, "total contribution sums correctly")
    print("  -> Scenario A PASS")


# ── Scenario B — document mismatch near top ─────────────────────────────────────
def test_scenario_b_document_mismatch():
    print("\nScenario B — document mismatch → Document Type Inconsistency near top")
    bd = [
        {"signal": "Elevated Country Risk", "points": 10, "source": "rule"},
        {"signal": "Document Type Inconsistency", "points": 25, "source": "doc_type_check"},
        {"signal": "High-Risk Occupation", "points": 20, "source": "rule"},
    ]
    contribs = generate_risk_breakdown(bd)
    _assert(contribs[0]["factor"] == "Document Type Inconsistency", "highest-impact factor is first")
    _assert(contribs[0]["category"] == "document", "categorised as 'document'")
    top = top_risk_drivers(contribs)
    _assert(any(d["factor"] == "Document Type Inconsistency" for d in top), "appears in Top Risk Drivers")
    print("  -> Scenario B PASS")


# ── Scenario C — high-risk country + PEP both visible ───────────────────────────
def test_scenario_c_country_and_pep():
    print("\nScenario C — high-risk country + PEP → both in Top Risk Drivers")
    bd = [
        {"signal": "PEP Match", "points": 25, "source": "rule"},
        {"signal": "Elevated Country Risk", "points": 10, "source": "rule"},
        {"signal": "Missing Source of Funds", "points": 5, "source": "rule"},
    ]
    contribs = generate_risk_breakdown(bd)
    top = top_risk_drivers(contribs, limit=3)
    factors = [d["factor"] for d in top]
    _assert("PEP Match" in factors, "PEP Match visible in top drivers")
    _assert("Elevated Country Risk" in factors, "country risk visible in top drivers")
    _assert(factors[0] == "PEP Match", "drivers sorted by impact (PEP first)")
    print("  -> Scenario C PASS")


# ── Scenario D — legacy case → graceful defaults ────────────────────────────────
def test_scenario_d_legacy():
    print("\nScenario D — legacy case → handled gracefully")
    legacy = KYCState.model_validate_json('{"case_id": "LEGACY"}')
    _assert(legacy.risk_contributions == [], "risk_contributions defaults to []")
    _assert(legacy.top_risk_drivers == [], "top_risk_drivers defaults to []")
    _assert(generate_risk_breakdown([]) == [], "empty breakdown yields empty contributions")
    _assert(generate_risk_breakdown(None) == [], "None breakdown handled safely")
    print("  -> Scenario D PASS")


# ── ML blend entry excluded from discrete contributions ─────────────────────────
def test_ml_entry_excluded():
    print("\nGuard — XGBoost blend entry excluded from discrete contributions")
    bd = [
        {"signal": "Sanctions Match", "points": 50, "source": "rule"},
        {"signal": "XGBoost ML Model (High, 80% confidence)", "points": 70, "source": "ml"},
    ]
    contribs = generate_risk_breakdown(bd)
    _assert(all("XGBoost" not in c["factor"] for c in contribs), "ML blend entry not listed as a factor")
    _assert(len(contribs) == 1 and contribs[0]["factor"] == "Sanctions Match", "only discrete rule factors remain")
    print("  -> Guard PASS")


# ── Risk Breakdown Agent must not change score/decision ─────────────────────────
def test_agent_does_not_change_score():
    print("\nGuard — Risk Breakdown Agent leaves score & decision untouched")
    s = _state_with_breakdown(
        [{"signal": "Sanctions Match", "points": 50, "source": "rule"},
         {"signal": "PEP Match", "points": 25, "source": "rule"}],
        risk_score=72,
    )
    s.decision = {"status": "ESCALATE", "requires_human_review": True}
    risk_before = dict(s.risk_assessment)
    decision_before = dict(s.decision)

    s = risk_breakdown_agent(s)

    _assert(s.risk_assessment == risk_before, "risk_assessment unchanged (score identical)")
    _assert(s.decision == decision_before, "decision unchanged")
    _assert(len(s.risk_contributions) == 2, "contributions recorded")
    _assert(len(s.top_risk_drivers) == 2, "top drivers recorded")
    _assert(bool(s.risk_breakdown_summary), "summary generated")
    _assert("risk_breakdown" in s.workflow_path, "step recorded in workflow_path")
    print("  -> Guard PASS")


if __name__ == "__main__":
    test_scenario_a_low_risk()
    test_scenario_b_document_mismatch()
    test_scenario_c_country_and_pep()
    test_scenario_d_legacy()
    test_ml_entry_excluded()
    test_agent_does_not_change_score()
    print("\nALL PHASE 3 SCENARIOS PASSED")
