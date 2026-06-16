import logging
import time
import uuid
from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from app.agents.adverse_media import adverse_media_agent
from app.agents.audit import audit_report_agent
from app.agents.base import log_event
from app.agents.confidence import confidence_agent
from app.agents.consistency import consistency_agent
from app.agents.copilot import copilot_agent
from app.agents.decision import decision_agent
from app.agents.document_extraction import document_extraction_agent
from app.agents.edd_summary import edd_summary_agent
from app.agents.edd_trigger import edd_trigger_agent
from app.agents.enhanced_due_diligence import enhanced_due_diligence_agent
from app.agents.entity_resolution import entity_resolution_agent
from app.agents.evidence_validation import evidence_validation_agent
from app.agents.explainability import explainability_agent
from app.agents.groq_verification import groq_verification_agent
from app.agents.financial import financial_profiling_agent
from app.agents.human_review import human_review_agent
from app.agents.indian_document_verification import indian_document_verification_agent
from app.agents.intake import intake_agent
from app.agents.normalization import normalization_agent
from app.agents.risk_breakdown import risk_breakdown_agent
from app.agents.risk_scoring import risk_scoring_agent
from app.agents.screening import compliance_screening_agent
from app.models.state import CustomerInput, KYCState

log = logging.getLogger(__name__)

STEP_DELAY_SEC = 0.45
PARALLEL_MAX_WORKERS = 4

# Maps the parallel-phase field on KYCState that each agent owns, so results can
# be merged back deterministically without concurrent mutation of shared state.
_PARALLEL_FIELDS = {
    "entity_resolution":     "entity_resolution",
    "compliance_screening":  "screening_results",
    "adverse_media":         "adverse_media",
    "evidence_validation":   "evidence_validation",
}


def _run_isolated_agent(base_state: KYCState, label: str, fn: Callable[[KYCState], Any]) -> dict[str, Any]:
    """
    Run one agent on an ISOLATED deep copy of the base state (so concurrent
    agents never mutate shared lists/dicts), capturing the field updates it
    produced, the audit/workflow deltas, timing, and any error.

    Never raises — a failing agent is captured so the pipeline can continue.
    """
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    work = base_state.model_copy(deep=True)
    base_audit = len(work.audit_log)
    base_wf = len(work.workflow_path)
    error: str | None = None
    try:
        fn(work)
    except Exception as exc:  # noqa: BLE001 — must isolate per-agent failure
        error = f"{type(exc).__name__}: {exc}"
        log.exception("Parallel agent '%s' failed", label)
    completed = datetime.now(timezone.utc)

    timing = {
        "agent": label,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "duration_ms": int((time.perf_counter() - t0) * 1000),
    }
    if error:
        timing["error"] = error

    return {
        "work": work,
        "new_events": work.audit_log[base_audit:],
        "new_wf": work.workflow_path[base_wf:],
        "timing": timing,
        "error": error,
    }


def _merge_parallel_result(state: KYCState, step_id: str, result: dict[str, Any]) -> None:
    """Merge one isolated agent's owned field back into the live state."""
    field = _PARALLEL_FIELDS.get(step_id)
    if field:
        setattr(state, field, getattr(result["work"], field))


class KYCOrchestrator:
    """Dynamic agentic orchestrator — routes investigation based on signals."""

    def run(self, customer: CustomerInput) -> KYCState:
        state = None
        for event in self.run_with_events(customer):
            if event.get("type") == "complete":
                state = KYCState.model_validate(event["state"])
        assert state is not None
        return state

    def run_with_events(self, customer: CustomerInput) -> Generator[dict[str, Any], None, None]:
        case_id = f"KYC-{uuid.uuid4().hex[:8].upper()}"
        state = KYCState(case_id=case_id)
        step_index = 0

        def emit(step_id: str, name: str, status: str, message: str, **extra: Any) -> dict[str, Any]:
            nonlocal step_index
            if status == "running":
                step_index += 1
            payload: dict[str, Any] = {
                "type": "step",
                "step_id": step_id,
                "step_name": name,
                "step_index": step_index,
                "status": status,
                "message": message,
                "case_id": case_id,
            }
            payload.update(extra)
            return payload

        def run_step(
            step_id: str,
            name: str,
            fn,
            start_msg: str,
            complete_msg: str | None = None,
            extra_on_complete: dict[str, Any] | None = None,
        ):
            nonlocal state
            yield emit(step_id, name, "running", start_msg)
            time.sleep(STEP_DELAY_SEC)
            _started = datetime.now(timezone.utc)
            _t0 = time.perf_counter()
            state = fn(state)
            state.agent_timings.append({
                "agent": name,
                "started_at": _started.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": int((time.perf_counter() - _t0) * 1000),
            })
            last_event = state.audit_log[-1] if state.audit_log else None
            msg = complete_msg or (last_event.action if last_event else "Completed")
            extras: dict[str, Any] = extra_on_complete or {}

            # Document extraction — surface missing fields
            if step_id == "document_extraction":
                missing     = state.document_extraction.get("fields_missing", [])
                missing_req = state.document_extraction.get("fields_missing_required", [])
                missing_opt = state.document_extraction.get("fields_missing_optional", [])
                extras = {
                    "missing_fields": missing,
                    "missing_required": missing_req,
                    "missing_optional": missing_opt,
                    "has_missing": bool(missing),
                }
                if missing:
                    msg = f"{msg} — missing: {', '.join(missing)}"

            # Indian document verification — surface verdict
            if step_id == "indian_document_verification":
                dv = state.document_verdict
                verdict = dv.get("verdict", "UNKNOWN")
                extras = {
                    "doc_verdict": verdict,
                    "has_rejection": verdict == "REJECTED",
                    "rejection_reasons": dv.get("rejection_reasons", []),
                    "verified_types": dv.get("verified_types", []),
                    "doc_type_mismatch": dv.get("document_type_mismatch", False),
                    "declared_doc_type": dv.get("declared_doc_type", ""),
                    "detected_doc_type": dv.get("detected_doc_type", ""),
                }
                if verdict == "REJECTED":
                    msg = f"REJECTED — {dv.get('summary', 'Document verification failed')}"
                elif verdict == "NEEDS_REVIEW":
                    msg = f"NEEDS REVIEW — {dv.get('summary', '')}"
                else:
                    msg = f"VERIFIED — {dv.get('summary', '')}"

            status_val = "warning" if extras.get("has_missing") or extras.get("doc_verdict") == "NEEDS_REVIEW" or extras.get("doc_type_mismatch") else "completed"
            if extras.get("doc_verdict") == "REJECTED":
                status_val = "rejected"
            yield emit(step_id, name, status_val, msg, **extras)

        # ── Pipeline start ────────────────────────────────────────────────────
        yield emit(
            "orchestrator", "Orchestrator Agent", "running",
            "Initiating dynamic KYC investigation workflow",
            customer=customer.name,
        )
        time.sleep(STEP_DELAY_SEC)
        state.workflow_path.append("orchestrator")
        log_event(state, "Orchestrator Agent", "Initiated dynamic KYC investigation workflow",
                  {"case_id": case_id, "customer": customer.name})
        yield emit("orchestrator", "Orchestrator Agent", "completed", "Workflow initialized")

        # ── Phase 1: Intake & extraction ─────────────────────────────────────
        yield from run_step(
            "intake", "Customer Intake Agent",
            lambda s: intake_agent(s, customer),
            "Accepting onboarding request...",
        )
        yield from run_step(
            "document_extraction", "Document Extraction Agent",
            document_extraction_agent,
            "Extracting and validating customer fields...",
        )
        yield from run_step(
            "groq_verification", "Groq Verification Agent",
            groq_verification_agent,
            "Groq AI verifying profile plausibility...",
        )
        yield from run_step(
            "normalization", "Profile Normalization Agent",
            normalization_agent,
            "Standardizing names, dates, and fields...",
        )

        # ── Phase 2: Indian Document Verification (XGBoost ML) ───────────────
        n_docs = len(state.uploaded_evidence)
        doc_start_msg = (
            f"Stage 1: Groq extracting fields from {n_docs} document(s), Stage 2: XGBoost ML classification..."
            if n_docs > 0
            else "No documents uploaded — checking document requirement..."
        )
        yield from run_step(
            "indian_document_verification",
            "Indian Document Verification Agent",
            indian_document_verification_agent,
            doc_start_msg,
        )

        # ── SHORT-CIRCUIT: Document REJECTED ─────────────────────────────────
        if state.document_verdict.get("pipeline_blocked"):
            verdict_summary = state.document_verdict.get("summary", "Document verification failed")
            rejection_reasons = state.document_verdict.get("rejection_reasons", [])

            yield emit(
                "orchestrator", "Orchestrator Agent", "running",
                "Document REJECTED — short-circuiting pipeline to ESCALATE",
                doc_verdict="REJECTED",
            )
            time.sleep(STEP_DELAY_SEC)
            log_event(
                state, "Orchestrator Agent",
                "Document rejection detected — bypassing investigation agents",
                {"reason": verdict_summary, "rejection_reasons": rejection_reasons},
            )

            # Skip all investigation agents — mark them as blocked
            skipped_agents = [
                ("entity_resolution",         "Entity Resolution Agent"),
                ("compliance_screening",       "Compliance Screening Agent"),
                ("adverse_media",              "Adverse Media Agent"),
                ("evidence_validation",        "Evidence Validation Agent"),
                ("financial_profiling",        "Financial Profiling Agent"),
                ("confidence",                 "Confidence Agent"),
                ("risk_scoring",               "Risk Scoring Agent"),
                ("edd_trigger",                "EDD Trigger Agent"),
                ("enhanced_due_diligence",     "Enhanced Due Diligence Agent"),
                ("edd_summary",                "EDD Summary Agent"),
                ("consistency",                "Consistency Agent"),
                ("risk_breakdown",             "Risk Breakdown Agent"),
                ("explainability",             "Explainability Agent"),
            ]
            for sid, sname in skipped_agents:
                yield emit(sid, sname, "skipped",
                           "Skipped — document rejected before this stage")

            # Still decompose the (rejection) risk breakdown so audit + UI have it.
            from app.services.risk_breakdown import (
                build_breakdown_summary, generate_risk_breakdown, top_risk_drivers,
            )
            _contribs = generate_risk_breakdown(state.risk_assessment.get("breakdown", []))
            state.risk_contributions = _contribs
            state.top_risk_drivers = top_risk_drivers(_contribs, limit=3)
            state.risk_breakdown_summary = build_breakdown_summary(_contribs)

            # Human review is mandatory for rejections
            yield from run_step(
                "decision", "Decision Agent",
                decision_agent,
                "Applying document rejection decision...",
            )
            yield from run_step(
                "copilot", "Compliance Copilot Agent",
                copilot_agent,
                "Generating executive case summary...",
            )
            yield from run_step(
                "human_review", "Human Review Agent",
                lambda s: human_review_agent(s),
                "Queuing rejected case for compliance officer review...",
            )
            yield from run_step(
                "audit_report", "Audit Report Agent",
                audit_report_agent,
                "Compiling rejection audit report...",
            )

            log_event(state, "Orchestrator Agent",
                      "Investigation complete — ESCALATE (document rejected)",
                      {"decision": state.decision.get("status")})
            yield emit(
                "orchestrator", "Orchestrator Agent", "completed",
                f"Investigation complete — {state.decision.get('status')} (document rejected)",
            )

            from app.agents.registry import build_agent_status
            yield {
                "type": "complete",
                "case_id": case_id,
                "state": state.model_dump(),
                "agent_status": build_agent_status(state.audit_log, state.workflow_path),
                "missing_fields": state.document_extraction.get("fields_missing", []),
                "document_rejected": True,
                "document_verdict": state.document_verdict,
            }
            return   # ← pipeline ends here for rejected documents

        # ── Phase 3+4: PARALLEL independent investigation ────────────────────
        # The four investigation agents run concurrently after document
        # verification. Dependency analysis:
        #   • Entity Resolution  — independent (reads customer_profile only)
        #   • Compliance Screening — depends on Entity Resolution (matches)
        #   • Adverse Media      — independent
        #   • Evidence Validation — depends on Adverse Media (evidence list)
        # All four are launched at once (so all show "running"); Screening and
        # Evidence internally await their dependency's result, preserving
        # identical output to the sequential pipeline while overlapping work.
        base_state = state.model_copy(deep=True)

        def entity_task() -> dict[str, Any]:
            def fn(work: KYCState) -> None:
                entity_resolution_agent(work)                 # basic pass
                if work.entity_resolution.get("matches"):     # deep-if-matches
                    entity_resolution_agent(work, deep=True)
            return _run_isolated_agent(base_state, "Entity Resolution Agent", fn)

        def adverse_task() -> dict[str, Any]:
            return _run_isolated_agent(base_state, "Adverse Media Agent", adverse_media_agent)

        def screening_task(entity_future: Future) -> dict[str, Any]:
            def fn(work: KYCState) -> None:
                er = entity_future.result()                   # await dependency
                if er and not er["error"]:
                    work.entity_resolution = er["work"].entity_resolution
                compliance_screening_agent(work)
            return _run_isolated_agent(base_state, "Compliance Screening Agent", fn)

        def evidence_task(adverse_future: Future) -> dict[str, Any]:
            def fn(work: KYCState) -> None:
                am = adverse_future.result()                  # await dependency
                if am and not am["error"]:
                    work.adverse_media = am["work"].adverse_media
                evidence_validation_agent(work)
            return _run_isolated_agent(base_state, "Evidence Validation Agent", fn)

        log_event(state, "Orchestrator Agent",
                  "Independent verification agents launched in parallel.",
                  {"agents": ["entity_resolution", "compliance_screening",
                              "adverse_media", "evidence_validation"]})
        yield emit("orchestrator_parallel_start", "Parallel Orchestration", "info",
                   "Independent verification agents launched in parallel.")

        results_by_sid: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=PARALLEL_MAX_WORKERS) as pool:
            f_entity   = pool.submit(entity_task)
            f_adverse  = pool.submit(adverse_task)
            f_screen   = pool.submit(screening_task, f_entity)
            f_evidence = pool.submit(evidence_task, f_adverse)
            future_map = {
                f_entity:   ("entity_resolution",    "Entity Resolution Agent"),
                f_screen:   ("compliance_screening", "Compliance Screening Agent"),
                f_adverse:  ("adverse_media",        "Adverse Media Agent"),
                f_evidence: ("evidence_validation",  "Evidence Validation Agent"),
            }

            # Emit "running" for all four immediately so the UI shows them concurrently.
            for fut, (sid, sname) in future_map.items():
                yield emit(sid, sname, "running", f"{sname} running (parallel)...")

            # Emit "completed" individually as each finishes; merge owned field now.
            for fut in as_completed(future_map):
                sid, sname = future_map[fut]
                res = fut.result()
                results_by_sid[sid] = res
                _merge_parallel_result(state, sid, res)
                if res["error"]:
                    state.parallel_errors.append({"agent": sname, "error": res["error"]})
                    yield emit(sid, sname, "warning",
                               f"{sname} error — {res['error']} (pipeline continued)")
                else:
                    last = res["work"].audit_log[-1] if res["work"].audit_log else None
                    yield emit(sid, sname, "completed",
                               last.action if last else f"{sname} completed")

        # Append audit / workflow / timings in a FIXED logical order so the
        # persisted audit trail is deterministic regardless of completion order.
        state.parallel_execution = True
        for sid in ("entity_resolution", "compliance_screening", "adverse_media", "evidence_validation"):
            res = results_by_sid.get(sid)
            if not res:
                continue
            state.audit_log.extend(res["new_events"])
            state.workflow_path.extend(res["new_wf"])
            state.agent_timings.append(res["timing"])

        # Reconcile the Adverse Media ↔ Evidence Validation cross-population that
        # the sequential pipeline produced (evidence tags High/Medium media).
        if state.evidence_validation and state.adverse_media:
            state.adverse_media["validated_evidence"] = (
                state.evidence_validation.get("adverse_media_validated", [])
            )

        log_event(state, "Orchestrator Agent", "Parallel verification phase completed.",
                  {"durations_ms": {r["timing"]["agent"]: r["timing"]["duration_ms"]
                                    for r in results_by_sid.values()},
                   "errors": state.parallel_errors})
        yield emit("orchestrator_parallel_done", "Parallel Orchestration", "info",
                   "Parallel verification phase completed.")

        # ── Conditional deep PEP confirmation (post-merge, depends on screening) ─
        screening = state.screening_results
        if screening.get("sanctions") or screening.get("pep"):
            yield from run_step(
                "entity_resolution_pep", "Entity Resolution Agent (PEP Confirm)",
                lambda s: entity_resolution_agent(s, deep=True),
                "Confirming sanctions/PEP entity match...",
            )

        # ── Phase 5: Financial profiling ──────────────────────────────────────
        if not state.customer_profile.get("source_of_funds"):
            yield emit(
                "orchestrator", "Orchestrator Agent", "warning",
                "Missing source of funds — flagged for financial review",
                missing_fields=["source_of_funds"],
            )
            log_event(state, "Orchestrator Agent",
                      "Missing source of funds — prioritizing financial investigation", {})

        yield from run_step(
            "financial_profiling", "Financial Profiling Agent",
            financial_profiling_agent,
            "Assessing occupation, country, and funds risk...",
        )

        # ── Phase 5b: Confidence aggregation (observational — never affects risk) ─
        yield from run_step(
            "confidence", "Confidence Agent",
            confidence_agent,
            "Aggregating verification confidence across agents...",
        )

        # ── Phase 6: Risk scoring + decision ──────────────────────────────────
        yield from run_step(
            "risk_scoring", "Risk Scoring Agent",
            risk_scoring_agent,
            "Aggregating risk signals with XGBoost model...",
        )

        # ── Phase 4: Dynamic Enhanced Due Diligence branch ───────────────────
        yield from run_step(
            "edd_trigger", "EDD Trigger Agent",
            edd_trigger_agent,
            "Evaluating enhanced due diligence triggers...",
        )
        if state.edd_triggered:
            log_event(state, "Orchestrator Agent",
                      "Enhanced Due Diligence required.",
                      {"reasons": state.edd_reasons})
            yield emit("orchestrator_edd", "EDD Orchestration", "info",
                       "Enhanced Due Diligence required.")
            yield from run_step(
                "enhanced_due_diligence", "Enhanced Due Diligence Agent",
                enhanced_due_diligence_agent,
                "Launching Enhanced Due Diligence workflow...",
            )
            yield from run_step(
                "edd_summary", "EDD Summary Agent",
                edd_summary_agent,
                "Compiling enhanced due diligence summary...",
            )
            log_event(state, "Orchestrator Agent", "EDD investigation completed.",
                      {"findings": len(state.edd_findings)})
            yield emit("orchestrator_edd_done", "EDD Orchestration", "info",
                       "EDD investigation completed.")
        else:
            log_event(state, "Orchestrator Agent", "EDD not required.", {})
            yield emit("orchestrator_edd", "EDD Orchestration", "info", "EDD not required.")
            yield emit("enhanced_due_diligence", "Enhanced Due Diligence Agent", "skipped",
                       "Skipped — EDD not triggered")
            yield emit("edd_summary", "EDD Summary Agent", "skipped",
                       "Skipped — EDD not triggered")

        # ── Phase 5: Cross-signal consistency analysis ───────────────────────
        yield from run_step(
            "consistency", "Consistency Agent",
            consistency_agent,
            "Analyzing cross-signal consistency of the customer profile...",
        )

        yield from run_step(
            "risk_breakdown", "Risk Breakdown Agent",
            risk_breakdown_agent,
            "Decomposing risk score into contributing factors...",
        )
        yield from run_step(
            "explainability", "Explainability Agent",
            explainability_agent,
            "Generating decision reasoning...",
        )
        yield from run_step(
            "decision", "Decision Agent",
            decision_agent,
            "Applying decision rules...",
        )
        yield from run_step(
            "copilot", "Compliance Copilot Agent",
            copilot_agent,
            "Generating executive case summary...",
        )

        # ── Phase 7: Human review ─────────────────────────────────────────────
        if state.decision.get("requires_human_review"):
            yield emit(
                "orchestrator", "Orchestrator Agent", "running",
                f"Routing to human review — {state.decision.get('status')}",
            )
            time.sleep(STEP_DELAY_SEC)
            yield from run_step(
                "human_review", "Human Review Agent",
                lambda s: human_review_agent(s),
                "Queuing case for compliance officer review...",
            )
        else:
            log_event(state, "Orchestrator Agent", "Low risk - auto-approve path",
                      {"decision": state.decision.get("status")})
            yield emit("human_review", "Human Review Agent", "skipped",
                       "Low risk — human review not required")

        # ── Phase 8: Audit ────────────────────────────────────────────────────
        yield from run_step(
            "audit_report", "Audit Report Agent",
            audit_report_agent,
            "Compiling audit report and evidence trail...",
        )
        log_event(state, "Orchestrator Agent", "Investigation complete",
                  {"decision": state.decision.get("status")})
        yield emit(
            "orchestrator", "Orchestrator Agent", "completed",
            f"Investigation complete — {state.decision.get('status')}",
        )

        from app.agents.registry import build_agent_status
        yield {
            "type": "complete",
            "case_id": case_id,
            "state": state.model_dump(),
            "agent_status": build_agent_status(state.audit_log, state.workflow_path),
            "missing_fields": state.document_extraction.get("fields_missing", []),
            "document_rejected": False,
            "document_verdict": state.document_verdict,
        }


orchestrator = KYCOrchestrator()
