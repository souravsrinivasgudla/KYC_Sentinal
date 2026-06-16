"""
EDD Trigger Agent (Phase 4).

Runs immediately after Risk Scoring. Evaluates whether Enhanced Due Diligence
is required (using existing signals only) and records the trigger reasons.
Observational — never changes risk, confidence, or the decision.
"""

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.edd import evaluate_edd_triggers


def edd_trigger_agent(state: KYCState) -> KYCState:
    result = evaluate_edd_triggers(state)
    state.edd_triggered = result["triggered"]
    state.edd_reasons = result["reasons"]
    state.workflow_path.append("edd_trigger")

    if state.edd_triggered:
        message = "High-risk profile detected. Enhanced Due Diligence required."
    else:
        message = "EDD not required — profile within standard due diligence thresholds."

    log_event(
        state,
        "EDD Trigger Agent",
        message,
        {"triggered": state.edd_triggered, "reasons": state.edd_reasons},
    )
    return state
