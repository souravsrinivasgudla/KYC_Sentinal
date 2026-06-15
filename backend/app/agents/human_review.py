from datetime import datetime, timezone

from app.agents.base import log_event
from app.models.state import HumanReviewInput, KYCState
from app.services.groq_client import human_review_assist


def human_review_agent(state: KYCState, review: HumanReviewInput | None = None) -> KYCState:
    if review is None:
        groq_briefing = human_review_assist(
            state.customer_profile,
            state.evidence_validation,
            state.risk_assessment,
            state.decision,
        )
        state.human_review = {
            "status": "pending",
            "required": state.decision.get("requires_human_review", False),
            "message": "Awaiting compliance officer review",
            "uploaded_evidence": state.uploaded_evidence,
            "evidence_validation": state.evidence_validation,
            "groq_officer_briefing": groq_briefing,
            "officer_checklist": groq_briefing.get("officer_checklist", []),
            "suggested_action": groq_briefing.get("suggested_action", "review"),
        }
        state.workflow_path.append("human_review_pending")
        log_event(
            state,
            "Human Review Agent",
            "Case queued for human review with Groq officer briefing",
            {
                "required": state.decision.get("requires_human_review"),
                "evidence_count": len(state.uploaded_evidence),
            },
        )
        return state

    final_status = review.action.upper()
    if review.action == "override":
        final_status = "APPROVE (OVERRIDE)"

    state.human_review = {
        **state.human_review,
        "status": "completed",
        "action": review.action,
        "final_decision": final_status,
        "comment": review.comment,
        "reviewer": review.reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "original_decision": state.decision.get("status"),
    }
    state.decision["final_status"] = final_status
    state.decision["human_reviewed"] = True
    state.workflow_path.append("human_review_completed")
    log_event(
        state,
        "Human Review Agent",
        f"Human decision: {review.action}",
        {"reviewer": review.reviewer, "comment": review.comment},
    )
    return state
