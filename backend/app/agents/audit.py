from datetime import datetime, timezone

from app.agents.base import log_event
from app.models.state import KYCState


def audit_report_agent(state: KYCState) -> KYCState:
    report = {
        "case_id": state.case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "customer_profile": state.customer_profile,
        "declared_document": {
            "document_type": state.customer_profile.get("document_type", ""),
            "document_number": state.customer_profile.get("id_number", ""),
        },
        "document_type_verification": _doc_type_verification(state),
        "document_extraction": state.document_extraction,
        "uploaded_evidence": state.uploaded_evidence,
        "groq_verification": state.groq_verification,
        "evidence_validation": state.evidence_validation,
        "entity_resolution": state.entity_resolution,
        "screening_results": {
            "sanctions": state.screening_results.get("sanctions"),
            "pep": state.screening_results.get("pep"),
            "confidence": state.screening_results.get("confidence"),
            "sanctions_hits": state.screening_results.get("sanctions_hits", []),
            "pep_hits": state.screening_results.get("pep_hits", []),
        },
        "adverse_media": state.adverse_media,
        "financial_profile": state.financial_profile,
        "risk_assessment": state.risk_assessment,
        "explanation": state.explanation,
        "decision": {
            k: v for k, v in state.decision.items() if k != "audit_report"
        },
        "human_review": state.human_review,
        "workflow_path": state.workflow_path,
        "agent_timeline": [e.model_dump() for e in state.audit_log],
        "evidence_collected": _collect_evidence(state),
        # Phase 1 — concurrent execution metadata
        "parallel_execution": state.parallel_execution,
        "agent_timings": state.agent_timings,
        "parallel_errors": state.parallel_errors,
        # Phase 2 — confidence framework (separate from risk)
        "overall_confidence": state.overall_confidence,
        "agent_confidences": state.agent_confidences,
        "confidence_summary": state.confidence_summary,
        # Phase 3 — risk contribution breakdown (explainability only)
        "risk_contributions": state.risk_contributions,
        "top_risk_drivers": state.top_risk_drivers,
        "risk_breakdown_summary": state.risk_breakdown_summary,
        # Phase 4 — enhanced due diligence (adaptive investigation)
        "edd_triggered": state.edd_triggered,
        "edd_reasons": state.edd_reasons,
        "edd_findings": state.edd_findings,
        "edd_summary": state.edd_summary,
        # Phase 5 — cross-signal consistency analysis (advisory only)
        "consistency_score": state.consistency_score,
        "consistency_summary": state.consistency_summary,
        "consistency_issues": state.consistency_issues,
        # Phase 6 — compliance copilot (executive summary + question log; no answers stored)
        "executive_summary": state.executive_summary,
        "copilot_queries": state.copilot_queries,
    }

    state.decision["audit_report"] = report
    state.workflow_path.append("audit_report")
    log_event(
        state,
        "Audit Report Agent",
        "Generated comprehensive audit report",
        {"evidence_count": len(report["evidence_collected"])},
    )
    return state


def _doc_type_verification(state: KYCState) -> dict:
    """Declared-vs-detected document-type result with its risk impact."""
    dtm = state.document_verdict.get("doc_type_match") or {}
    return {
        "declared_doc_type": state.document_verdict.get("declared_doc_type")
        or state.customer_profile.get("document_type", ""),
        "detected_doc_type": state.document_verdict.get("detected_doc_type", ""),
        "document_type_mismatch": state.document_verdict.get("document_type_mismatch", False),
        "mismatch_severity": state.document_verdict.get("mismatch_severity", "NONE"),
        "match_result": "MISMATCH" if state.document_verdict.get("document_type_mismatch") else "MATCH",
        "risk_impact_points": dtm.get("points", 0),
        "reason": dtm.get("reason", ""),
    }


def _collect_evidence(state: KYCState) -> list[dict]:
    evidence: list[dict] = []

    for hit in state.screening_results.get("sanctions_hits", []):
        evidence.append({"type": "sanctions", "detail": hit})
    for hit in state.screening_results.get("pep_hits", []):
        evidence.append({"type": "pep", "detail": hit})
    for article in state.adverse_media.get("evidence", []):
        evidence.append({"type": "adverse_media", "detail": article})
    for factor in state.financial_profile.get("factors", []):
        evidence.append({"type": "financial_factor", "detail": factor})

    return evidence
