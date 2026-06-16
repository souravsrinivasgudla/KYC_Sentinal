"""
Phase 1 — Parallel Agent Execution validation.

Tests the ORCHESTRATION STRATEGY (concurrency, merge, timing, short-circuit,
error isolation) deterministically by replacing every agent with a fast fake,
so no Groq / vector / XGBoost dependency is needed.

Run:  python test_phase1_parallel.py     (or: pytest test_phase1_parallel.py)

Scenario A — normal customer: all four parallel agents execute & overlap.
Scenario B — document rejection: no parallel agents start.
Scenario C — one parallel agent fails: error captured, audit updated, pipeline continues.
"""
from __future__ import annotations

import threading
import time
from unittest import mock

from app.agents.base import log_event
from app.models.state import CustomerInput, KYCState
from app.orchestrator import graph

CUSTOMER = CustomerInput(
    name="Test User", dob="1990-01-01", nationality="IN",
    occupation="Engineer", source_of_funds="Salary",
    document_type="PAN Card", id_number="ABCDE1234F",
)

PARALLEL_IDS = ["entity_resolution", "compliance_screening", "adverse_media", "evidence_validation"]


# ── Fake agents ────────────────────────────────────────────────────────────────
_exec_log: list[tuple[str, float, float]] = []
_exec_lock = threading.Lock()
AGENT_SLEEP = 0.15  # so concurrent agents demonstrably overlap


def _record(name: str, start: float, end: float) -> None:
    with _exec_lock:
        _exec_log.append((name, start, end))


def _simple(field: str, value, wf: str, agent_name: str):
    def fn(state: KYCState, *args, **kwargs) -> KYCState:
        t0 = time.perf_counter()
        time.sleep(AGENT_SLEEP)
        setattr(state, field, value)
        state.workflow_path.append(wf)
        log_event(state, agent_name, f"{agent_name} done", {})
        _record(agent_name, t0, time.perf_counter())
        return state
    return fn


def _doc_verification(blocked: bool):
    def fn(state: KYCState) -> KYCState:
        state.document_verdict = {
            "verdict": "REJECTED" if blocked else "VERIFIED",
            "summary": "fake",
            "pipeline_blocked": blocked,
            "rejection_reasons": ["fake rejection"] if blocked else [],
            "document_type_mismatch": False,
            "per_document": [],
        }
        state.workflow_path.append("indian_document_verification")
        log_event(state, "Indian Document Verification Agent", "fake", {})
        return state
    return fn


def _failing(agent_name: str):
    def fn(state: KYCState, *a, **k) -> KYCState:
        time.sleep(AGENT_SLEEP)
        raise RuntimeError("simulated agent failure")
    return fn


def _passthrough(wf: str, agent_name: str):
    def fn(state: KYCState, *a, **k) -> KYCState:
        state.workflow_path.append(wf)
        log_event(state, agent_name, "fake", {})
        return state
    return fn


def _base_patches(doc_blocked: bool):
    """Patch every agent in the graph module with a fast fake."""
    return {
        "intake_agent": lambda s, c: _passthrough("intake", "Customer Intake Agent")(s),
        "document_extraction_agent": _passthrough("document_extraction", "Document Extraction Agent"),
        "groq_verification_agent": _passthrough("groq_verification", "Groq Verification Agent"),
        "normalization_agent": _passthrough("normalization", "Profile Normalization Agent"),
        "indian_document_verification_agent": _doc_verification(doc_blocked),
        "entity_resolution_agent": _simple("entity_resolution", {"matches": []}, "entity_resolution", "Entity Resolution Agent"),
        "compliance_screening_agent": _simple("screening_results", {"sanctions": False, "pep": False}, "compliance_screening", "Compliance Screening Agent"),
        "adverse_media_agent": _simple("adverse_media", {"match": False, "evidence": []}, "adverse_media", "Adverse Media Agent"),
        "evidence_validation_agent": _simple("evidence_validation", {"validation_passed": True, "adverse_media_validated": []}, "evidence_validation", "Evidence Validation Agent"),
        "financial_profiling_agent": _passthrough("financial_profiling", "Financial Profiling Agent"),
        "risk_scoring_agent": _passthrough("risk_scoring", "Risk Scoring Agent"),
        "explainability_agent": _passthrough("explainability", "Explainability Agent"),
        "decision_agent": lambda s: (s.decision.update({"status": "APPROVE", "requires_human_review": False}) or s),
        "human_review_agent": _passthrough("human_review", "Human Review Agent"),
        "audit_report_agent": lambda s: (s.decision.update({"audit_report": {"parallel_execution": s.parallel_execution, "agent_timings": s.agent_timings, "parallel_errors": s.parallel_errors}}) or s),
    }


def _run(patches: dict):
    _exec_log.clear()
    events: list[dict] = []
    final: KYCState | None = None
    with mock.patch.multiple(graph, **patches):
        for ev in graph.orchestrator.run_with_events(CUSTOMER):
            events.append(ev)
            if ev.get("type") == "complete":
                final = KYCState.model_validate(ev["state"])
    return events, final


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  ✓ {msg}")


# ── Scenario A ──────────────────────────────────────────────────────────────────
def test_scenario_a_normal_parallel():
    print("\nScenario A — normal customer: parallel agents execute & overlap")
    events, final = _run(_base_patches(doc_blocked=False))
    assert final is not None

    for sid in PARALLEL_IDS:
        _assert(sid in final.workflow_path, f"{sid} executed")
    _assert(final.parallel_execution is True, "parallel_execution flag set")

    timed = {t["agent"] for t in final.agent_timings}
    for name in ["Entity Resolution Agent", "Compliance Screening Agent", "Adverse Media Agent", "Evidence Validation Agent"]:
        _assert(name in timed, f"timing recorded for {name}")
    _assert(all("duration_ms" in t and "started_at" in t and "completed_at" in t for t in final.agent_timings),
            "every timing has duration_ms/started_at/completed_at")

    # All four "running" events emitted before any parallel "completed" event.
    step_events = [e for e in events if e.get("type") == "step"]
    running_idx = [i for i, e in enumerate(step_events) if e["step_id"] in PARALLEL_IDS and e["status"] == "running"]
    completed_idx = [i for i, e in enumerate(step_events) if e["step_id"] in PARALLEL_IDS and e["status"] in ("completed", "warning")]
    _assert(len(running_idx) == 4, "4 parallel 'running' events emitted")
    _assert(max(running_idx) < min(completed_idx), "all 'running' emitted before any parallel 'completed'")

    # Orchestration notes present.
    notes = [e for e in step_events if e["step_id"].startswith("orchestrator_parallel")]
    _assert(any("launched in parallel" in e["message"] for e in notes), "launch note emitted")
    _assert(any("phase completed" in e["message"] for e in notes), "completion note emitted")

    # Concurrency: independent agents (entity & adverse) overlap in wall-clock time.
    spans = {n: (s, e) for n, s, e in _exec_log}
    es, ee = spans["Entity Resolution Agent"]
    as_, ae = spans["Adverse Media Agent"]
    _assert(es < ae and as_ < ee, "Entity Resolution and Adverse Media intervals overlap (concurrent)")
    print("  → Scenario A PASS")


# ── Scenario B ──────────────────────────────────────────────────────────────────
def test_scenario_b_document_rejection():
    print("\nScenario B — document rejection: no parallel agents start")
    events, final = _run(_base_patches(doc_blocked=True))
    assert final is not None

    for sid in PARALLEL_IDS:
        _assert(sid not in final.workflow_path, f"{sid} did NOT execute")
    _assert(final.parallel_execution is False, "parallel_execution stayed False")
    _assert(len(_exec_log) == 0, "no parallel agent bodies ran")

    step_events = [e for e in events if e.get("type") == "step"]
    skipped = {e["step_id"] for e in step_events if e["status"] == "skipped"}
    for sid in PARALLEL_IDS:
        _assert(sid in skipped, f"{sid} emitted as skipped")
    _assert(any(e.get("document_rejected") for e in events if e.get("type") == "complete"), "document_rejected in result")
    print("  → Scenario B PASS")


# ── Scenario C ──────────────────────────────────────────────────────────────────
def test_scenario_c_parallel_agent_failure():
    print("\nScenario C — one parallel agent fails: error captured, pipeline continues")
    patches = _base_patches(doc_blocked=False)
    patches["adverse_media_agent"] = _failing("Adverse Media Agent")
    events, final = _run(patches)
    assert final is not None

    _assert(len(final.parallel_errors) >= 1, "parallel error captured in state")
    _assert(any(pe["agent"] == "Adverse Media Agent" for pe in final.parallel_errors),
            "Adverse Media Agent failure recorded")

    step_events = [e for e in events if e.get("type") == "step"]
    warn = [e for e in step_events if e["step_id"] == "adverse_media" and e["status"] == "warning"]
    _assert(len(warn) == 1, "failed agent emitted a 'warning' step (not a crash)")

    # Pipeline continued: other parallel agents + downstream still ran.
    _assert("entity_resolution" in final.workflow_path, "Entity Resolution still ran")
    _assert("compliance_screening" in final.workflow_path, "Compliance Screening still ran")
    _assert("evidence_validation" in final.workflow_path, "Evidence Validation still ran (dependency degraded gracefully)")
    _assert(final.decision.get("status") == "APPROVE", "pipeline reached a final decision")

    # Audit updated with parallel metadata + the error.
    audit = final.decision.get("audit_report", {})
    _assert(audit.get("parallel_execution") is True, "audit reports parallel_execution")
    _assert(len(audit.get("parallel_errors", [])) >= 1, "audit reports the parallel error")
    print("  → Scenario C PASS")


if __name__ == "__main__":
    test_scenario_a_normal_parallel()
    test_scenario_b_document_rejection()
    test_scenario_c_parallel_agent_failure()
    print("\nALL SCENARIOS PASSED ✅")
