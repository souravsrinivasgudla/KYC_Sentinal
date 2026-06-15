from app.agents.base import log_event
from app.models.state import KYCState


def decision_agent(state: KYCState) -> KYCState:
    # Use the (potentially bumped) score from explainability agent
    score = state.risk_assessment.get("risk_score", 0)

    if score >= 70:
        decision = "ESCALATE"
        requires_review = True
    elif score >= 40:
        decision = "REVIEW"
        requires_review = True
    else:
        decision = "APPROVE"
        requires_review = False

    explanation = state.explanation
    id_mismatch = explanation.get("id_mismatch")

    # Wrong ID entered vs correct document must never auto-approve
    if id_mismatch and score < 45:
        score = 45
        decision = "REVIEW"
        requires_review = True
        state.risk_assessment = {
            **state.risk_assessment,
            "risk_score": score,
            "risk_level": "Medium",
        }

    state.decision = {
        "status":                decision,
        "risk_score":            score,
        "risk_level":            state.risk_assessment.get("risk_level"),
        "requires_human_review": requires_review,
        "auto_decision":         not requires_review,
        "reasons":               explanation.get("reasons", []),
        "urgency":               explanation.get("urgency", "standard"),
        "groq_powered":          explanation.get("groq_powered", False),
        # Surface id_mismatch at decision level for the UI
        "id_mismatch": {
            "detected":   True,
            "declared":   id_mismatch["declared"],
            "extracted":  id_mismatch["extracted"],
            "reason":     id_mismatch["short_reason"],
        } if id_mismatch else None,
    }
    state.workflow_path.append("decision")
    log_event(
        state,
        "Decision Agent",
        f"Decision: {decision}" + (" | ID mismatch" if id_mismatch else ""),
        {
            "score":          score,
            "requires_review": requires_review,
            "id_mismatch":    bool(id_mismatch),
        },
    )
    return state
