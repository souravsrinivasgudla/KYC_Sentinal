import time
import uuid
from collections.abc import Generator
from typing import Any

from app.agents.adverse_media import adverse_media_agent
from app.agents.audit import audit_report_agent
from app.agents.base import log_event
from app.agents.decision import decision_agent
from app.agents.document_extraction import document_extraction_agent
from app.agents.entity_resolution import entity_resolution_agent
from app.agents.evidence_validation import evidence_validation_agent
from app.agents.explainability import explainability_agent
from app.agents.groq_verification import groq_verification_agent
from app.agents.financial import financial_profiling_agent
from app.agents.human_review import human_review_agent
from app.agents.indian_document_verification import indian_document_verification_agent
from app.agents.intake import intake_agent
from app.agents.normalization import normalization_agent
from app.agents.risk_scoring import risk_scoring_agent
from app.agents.screening import compliance_screening_agent
from app.models.state import CustomerInput, KYCState

STEP_DELAY_SEC = 0.45


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
            state = fn(state)
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
                ("risk_scoring",               "Risk Scoring Agent"),
                ("explainability",             "Explainability Agent"),
            ]
            for sid, sname in skipped_agents:
                yield emit(sid, sname, "skipped",
                           "Skipped — document rejected before this stage")

            # Human review is mandatory for rejections
            yield from run_step(
                "decision", "Decision Agent",
                decision_agent,
                "Applying document rejection decision...",
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

        # ── Phase 3: Identity screening ───────────────────────────────────────
        yield from run_step(
            "entity_resolution", "Entity Resolution Agent",
            lambda s: entity_resolution_agent(s),
            "Comparing identity against watchlists...",
        )

        matches = state.entity_resolution.get("matches", [])
        if matches:
            yield emit(
                "orchestrator", "Orchestrator Agent", "running",
                f"Routing to deep entity resolution ({len(matches)} matches)",
            )
            time.sleep(STEP_DELAY_SEC)
            log_event(state, "Orchestrator Agent", "Routing to deep entity resolution",
                      {"match_count": len(matches)})
            yield from run_step(
                "entity_resolution_deep", "Entity Resolution Agent (Deep)",
                lambda s: entity_resolution_agent(s, deep=True),
                "Running deep fuzzy match analysis...",
            )

        yield from run_step(
            "compliance_screening", "Compliance Screening Agent",
            compliance_screening_agent,
            "Screening sanctions, watchlists, and PEP...",
        )

        screening = state.screening_results
        if screening.get("sanctions") or screening.get("pep"):
            yield emit(
                "orchestrator", "Orchestrator Agent", "running",
                "Sanctions/PEP hit — deep entity resolution",
            )
            time.sleep(STEP_DELAY_SEC)
            log_event(state, "Orchestrator Agent", "Sanctions/PEP hit detected",
                      {"sanctions": screening.get("sanctions"), "pep": screening.get("pep")})
            yield from run_step(
                "entity_resolution_pep", "Entity Resolution Agent (PEP Confirm)",
                lambda s: entity_resolution_agent(s, deep=True),
                "Confirming sanctions/PEP entity match...",
            )

        yield from run_step(
            "adverse_media", "Adverse Media Agent",
            adverse_media_agent,
            "Searching adverse media and regulatory notices...",
        )

        # ── Phase 4: Evidence validation (Groq LLM semantic) ─────────────────
        # Document structure already verified by ML above;
        # this step does deeper semantic / content validation via Groq
        yield from run_step(
            "evidence_validation", "Evidence Validation Agent",
            evidence_validation_agent,
            f"Groq cross-checking document content against customer profile ({n_docs} doc(s))...",
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

        # ── Phase 6: Risk scoring + decision ──────────────────────────────────
        yield from run_step(
            "risk_scoring", "Risk Scoring Agent",
            risk_scoring_agent,
            "Aggregating risk signals with XGBoost model...",
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
