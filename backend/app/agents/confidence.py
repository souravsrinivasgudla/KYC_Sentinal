"""
Confidence Agent (Phase 2).

Runs after Financial Profiling and before Risk Scoring. It collects the existing
confidence signals from the verification agents, computes a single overall
confidence score, and generates a human-readable confidence summary.

This agent is observational only — it never modifies risk scoring, decisions,
or any other agent's output.
"""

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.confidence import (
    build_confidence_summary,
    calculate_overall_confidence,
    confidence_band,
    extract_agent_confidences,
)


def confidence_agent(state: KYCState) -> KYCState:
    agent_confidences = extract_agent_confidences(state)
    overall = calculate_overall_confidence(agent_confidences)
    summary = build_confidence_summary(overall, agent_confidences)

    state.agent_confidences = agent_confidences
    state.overall_confidence = overall
    state.confidence_summary = summary
    state.workflow_path.append("confidence")

    log_event(
        state,
        "Confidence Agent",
        f"Overall verification confidence: {round(overall * 100)}% ({confidence_band(overall)})",
        {
            "overall_confidence": overall,
            "agent_confidences": agent_confidences,
            "summary": summary,
        },
    )
    return state
