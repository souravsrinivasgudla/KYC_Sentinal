from datetime import datetime, timezone

from app.agents.base import log_event
from app.models.state import KYCState


def audit_report_agent(state: KYCState) -> KYCState:
    report = {
        "case_id": state.case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "customer_profile": state.customer_profile,
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
