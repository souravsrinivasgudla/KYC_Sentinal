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
    name_mismatch = explanation.get("name_mismatch")

    # Any entered-vs-document detail mismatch must go to a human reviewer with a
    # recommendation — never auto-approve.
    review_recommendation = state.document_verdict.get("review_recommendation")
    if review_recommendation and review_recommendation.get("force_review") and decision == "APPROVE":
        score = max(score, 45)
        decision = "REVIEW"
        requires_review = True
        state.risk_assessment = {
            **state.risk_assessment,
            "risk_score": score,
            "risk_level": state.risk_assessment.get("risk_level") or "Medium",
        }

    # Wrong ID or name vs document must never auto-approve
    if (id_mismatch or name_mismatch) and score < 45:
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
        "name_mismatch": {
            "detected":   True,
            "declared":   name_mismatch["declared"],
            "extracted":  name_mismatch["extracted"],
            "reason":     name_mismatch["short_reason"],
        } if name_mismatch else None,
        # Reviewer guidance for entered-vs-document detail mismatches.
        "review_recommendation": review_recommendation,
    }
    state.workflow_path.append("decision")
    log_event(
        state,
        "Decision Agent",
        f"Decision: {decision}" + (" | ID mismatch" if id_mismatch else "") + (" | Name mismatch" if name_mismatch else ""),
        {
            "score":          score,
            "requires_review": requires_review,
            "id_mismatch":    bool(id_mismatch),
            "name_mismatch":  bool(name_mismatch),
        },
    )
    return state
