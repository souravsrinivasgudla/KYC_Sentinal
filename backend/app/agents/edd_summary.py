"""
EDD Summary Agent (Phase 4).

Produces a concise narrative of why Enhanced Due Diligence was triggered and
what the deeper review found. Runs only when EDD is active. Observational only.
"""

from app.agents.base import log_event
from app.models.state import KYCState


def _join(items: list[str], limit: int) -> str:
    picked = [i.rstrip(".") for i in items[:limit]]
    if not picked:
        return ""
    if len(picked) == 1:
        return picked[0]
    return ", ".join(picked[:-1]) + f" and {picked[-1]}"


def edd_summary_agent(state: KYCState) -> KYCState:
    reasons = state.edd_reasons or []
    findings = state.edd_findings or []

    reason_text = _join(reasons, 2).lower() or "elevated risk indicators"
    finding_text = _join(findings, 3) or "no additional adverse findings"

    summary = (
        f"Enhanced Due Diligence was triggered due to {reason_text}. "
        f"Additional review identified: {finding_text}."
    )

    state.edd_summary = summary
    state.workflow_path.append("edd_summary")
    log_event(
        state,
        "EDD Summary Agent",
        "Enhanced Due Diligence summary generated.",
        {"summary": summary},
    )
    return state
