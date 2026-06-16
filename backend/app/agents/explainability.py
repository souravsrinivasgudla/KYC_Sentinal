"""
Explainability Agent — Groq one-liner escalation reasons + ID cross-check.
"""

import logging

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.id_cross_check import check_id_mismatch

log = logging.getLogger(__name__)

ID_MISMATCH_POINTS = 35


def _risk_level_from_score(score: int) -> str:
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def explainability_agent(state: KYCState) -> KYCState:
    from app.services.groq_client import generate_escalation_reasons

    risk = state.risk_assessment
    score = risk.get("risk_score", 0)
    breakdown = list(risk.get("breakdown", []))

    if score >= 70:
        decision_hint = "ESCALATE"
    elif score >= 40:
        decision_hint = "REVIEW"
    else:
        decision_hint = "APPROVE"

    # ID cross-check (may not yet be in breakdown if risk_scoring missed it)
    id_mismatch = state.document_verdict.get("id_mismatch") or check_id_mismatch(
        state.customer_profile.get("id_number", ""),
        state.document_verdict,
    )

    if id_mismatch and not any(b.get("signal") == "ID Number Mismatch" for b in breakdown):
        breakdown.append({
            "signal": "ID Number Mismatch",
            "points": ID_MISMATCH_POINTS,
            "source": "id_cross_check",
        })
        score = min(score + ID_MISMATCH_POINTS, 100)
        if score >= 70:
            decision_hint = "ESCALATE"
        elif score >= 40:
            decision_hint = "REVIEW"

    state.risk_assessment = {
        **risk,
        "risk_score": score,
        "risk_level": _risk_level_from_score(score),
        "breakdown": breakdown,
    }

    # Groq one-liner reasons for ESCALATE / REVIEW
    groq_reasons: list[str] = []
    groq_summary = ""
    groq_urgency = "standard"
    groq_powered = False

    if decision_hint in ("ESCALATE", "REVIEW"):
        try:
            result = generate_escalation_reasons(
                decision=decision_hint,
                risk_score=score,
                risk_level=state.risk_assessment.get("risk_level", "High"),
                breakdown=breakdown,
                customer_profile=state.customer_profile,
                document_verdict=state.document_verdict or None,
                id_mismatch=id_mismatch,
            )
            groq_reasons = result.get("reasons", [])
            groq_summary = result.get("summary", "")
            groq_urgency = result.get("urgency", "standard")
            groq_powered = result.get("groq_powered", False)
        except Exception as exc:
            log.warning("Groq escalation reasons failed: %s", exc)

    if not groq_reasons:
        groq_reasons = [
            f"{item['signal']} contributed to this decision."
            for item in breakdown
            if item.get("points", 0) >= 10
        ]
        if id_mismatch:
            groq_reasons.insert(0, id_mismatch["short_reason"])
        if not groq_reasons:
            groq_reasons = ["Risk score exceeds approval threshold."]

    # Always surface ID mismatch as first reason
    if id_mismatch:
        short = id_mismatch["short_reason"]
        if not any(short.lower()[:25] in r.lower() for r in groq_reasons):
            groq_reasons.insert(0, short)

    # Surface declared-vs-detected document-type mismatch
    doc_type_match = state.document_verdict.get("doc_type_match")
    if doc_type_match and doc_type_match.get("document_type_mismatch"):
        dt_reason = doc_type_match.get("reason", "")
        if dt_reason and not any(dt_reason.lower()[:30] in r.lower() for r in groq_reasons):
            groq_reasons.insert(0, dt_reason)

    narrative = groq_summary or (
        f"Decision: {decision_hint}. Risk score {score}/100.\n"
        + "\n".join(f"• {r}" for r in groq_reasons)
    )

    # ── Confidence commentary (Phase 2) — appended, never replaces existing text ─
    from app.services.confidence import confidence_band

    overall_conf = state.overall_confidence
    band = confidence_band(overall_conf)
    confidence_commentary = {
        "High": "The verification outcome is supported by high-confidence document analysis and screening results.",
        "Moderate": "The verification outcome is supported by moderate-confidence evidence and may benefit from manual review.",
        "Low": "The verification outcome relies on lower-confidence signals and should be reviewed carefully.",
    }[band]
    narrative = f"{narrative}\n\n{confidence_commentary}"

    # ── Risk driver commentary (Phase 3) — appended, never replaces ─────────────
    risk_drivers_commentary = ""
    drivers = state.top_risk_drivers or state.risk_contributions[:2]
    if drivers:
        def _fmt(d):
            imp = d.get("impact", 0)
            return f"{d.get('factor')} ({'+' if imp >= 0 else ''}{imp})"
        top2 = drivers[:2]
        joined = " and ".join(_fmt(d) for d in top2)
        risk_drivers_commentary = f"The primary risk drivers were {joined}."
        narrative = f"{narrative}\n\n{risk_drivers_commentary}"

    # ── EDD commentary (Phase 4) — appended, never replaces ─────────────────────
    edd_commentary = ""
    if state.edd_triggered:
        edd_commentary = "Enhanced Due Diligence was performed due to elevated risk indicators."
        if state.edd_summary:
            edd_commentary = f"{edd_commentary} {state.edd_summary}"
        narrative = f"{narrative}\n\n{edd_commentary}"

    # ── Consistency commentary (Phase 5) — appended, never replaces ─────────────
    consistency_commentary = ""
    if state.consistency_issues:
        consistency_commentary = state.consistency_summary or (
            "Profile consistency analysis identified cross-signal discrepancies."
        )
        narrative = f"{narrative}\n\n{consistency_commentary}"

    state.explanation = {
        "decision_hint": decision_hint,
        "reasons": groq_reasons,
        "narrative": narrative,
        "risk_level": state.risk_assessment.get("risk_level"),
        "risk_score": score,
        "groq_powered": groq_powered,
        "urgency": groq_urgency,
        "id_mismatch": id_mismatch,
        "document_type_mismatch": doc_type_match if (doc_type_match and doc_type_match.get("document_type_mismatch")) else None,
        "confidence_commentary": confidence_commentary,
        "overall_confidence": overall_conf,
        "risk_drivers_commentary": risk_drivers_commentary,
        "top_risk_drivers": state.top_risk_drivers,
        "edd_commentary": edd_commentary,
        "edd_triggered": state.edd_triggered,
        "consistency_commentary": consistency_commentary,
        "consistency_score": state.consistency_score,
    }

    state.workflow_path.append("explainability")
    log_event(
        state,
        "Explainability Agent",
        f"Generated {'Groq' if groq_powered else 'template'} one-liner reasons [{decision_hint}]",
        {
            "reasons": groq_reasons[:4],
            "id_mismatch": bool(id_mismatch),
            "groq_powered": groq_powered,
        },
    )
    return state
