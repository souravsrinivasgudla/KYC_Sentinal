"""
Consistency Agent (Phase 5).

Runs after the EDD branch and before Risk Breakdown for all non-rejected cases.
Detects cross-signal contradictions (occupation vs funds, nationality vs
documents, age vs occupation, document-type contradictions, missing critical
info), computes an informational consistency score, and writes a summary.

Read-only / advisory — never changes risk, confidence, EDD, or the decision.
"""

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.consistency import (
    build_consistency_summary,
    calculate_consistency_score,
    detect_consistency_issues,
)


def consistency_agent(state: KYCState) -> KYCState:
    issues = detect_consistency_issues(state)
    score = calculate_consistency_score(issues)
    summary = build_consistency_summary(issues, score)

    state.consistency_issues = issues
    state.consistency_score = score
    state.consistency_summary = summary
    state.workflow_path.append("consistency")

    log_event(
        state,
        "Consistency Agent",
        f"Cross-signal consistency analysis completed — {len(issues)} issue(s), score {round(score * 100)}%.",
        {"issues": issues, "consistency_score": score, "summary": summary},
    )
    return state
