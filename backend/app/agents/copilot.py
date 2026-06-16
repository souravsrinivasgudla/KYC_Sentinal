"""
Copilot Agent (Phase 6).

Generates an investigation-ready executive summary from the case's existing
findings. Runs after Explainability/Decision so it can reference the final
disposition. Read-only — it changes no decision, score, or finding.
"""

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.copilot import build_executive_summary


def copilot_agent(state: KYCState) -> KYCState:
    summary = build_executive_summary(state)
    state.executive_summary = summary
    state.workflow_path.append("copilot")
    log_event(
        state,
        "Compliance Copilot Agent",
        "Executive case summary generated.",
        {"executive_summary": summary},
    )
    return state
