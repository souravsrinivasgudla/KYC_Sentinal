"""
Risk Breakdown Agent (Phase 3).

Runs after Risk Scoring and before Explainability. It decomposes the already-
computed risk score into per-factor contributions, identifies the top drivers,
and generates a summary.

Observational only — it never modifies the risk score, weights, or decision.
"""

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.risk_breakdown import (
    build_breakdown_summary,
    generate_risk_breakdown,
    top_risk_drivers,
)


def risk_breakdown_agent(state: KYCState) -> KYCState:
    breakdown = state.risk_assessment.get("breakdown", [])
    contributions = generate_risk_breakdown(breakdown)
    drivers = top_risk_drivers(contributions, limit=3)
    summary = build_breakdown_summary(contributions)

    state.risk_contributions = contributions
    state.top_risk_drivers = drivers
    state.risk_breakdown_summary = summary
    state.workflow_path.append("risk_breakdown")

    log_event(
        state,
        "Risk Breakdown Agent",
        summary,
        {
            "risk_contributions": contributions,
            "top_risk_drivers": drivers,
        },
    )
    return state
