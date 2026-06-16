"""
Compliance Investigation Copilot (Phase 6).

A READ-ONLY assistant that answers natural-language questions about a completed
case using ONLY data already produced by the pipeline. It never changes
decisions, scores, confidence, or findings, and it never invents facts.

Recognised questions are answered deterministically from case data. Anything
else falls back to a grounded Groq call constrained to the supplied context.
"""

from __future__ import annotations

import json
from typing import Any

UNAVAILABLE = "That information is not available in this case."


# ── Context + summary ───────────────────────────────────────────────────────────

def build_case_context(state) -> dict[str, Any]:
    """Structured, hallucination-free snapshot of the case for Q&A and the UI card."""
    decision = state.decision or {}
    risk = state.risk_assessment or {}
    screening = state.screening_results or {}
    dv = state.document_verdict or {}
    media = state.adverse_media or {}
    return {
        "customer_name": (state.customer_profile or {}).get("name", ""),
        "decision": decision.get("status", "PENDING"),
        "final_status": decision.get("final_status"),
        "requires_human_review": decision.get("requires_human_review", False),
        "human_reviewed": decision.get("human_reviewed", False),
        "risk_score": risk.get("risk_score", 0),
        "risk_level": risk.get("risk_level", "Unknown"),
        "confidence": state.overall_confidence,
        "decision_reasons": decision.get("reasons") or (state.explanation or {}).get("reasons", []),
        "explanation": (state.explanation or {}).get("narrative", ""),
        "top_risk_drivers": state.top_risk_drivers,
        "risk_contributions": state.risk_contributions,
        "edd_triggered": state.edd_triggered,
        "edd_reasons": state.edd_reasons,
        "edd_findings": state.edd_findings,
        "edd_summary": state.edd_summary,
        "consistency_score": state.consistency_score,
        "consistency_summary": state.consistency_summary,
        "consistency_issues": state.consistency_issues,
        "sanctions_match": screening.get("sanctions", False),
        "pep_match": screening.get("pep", False),
        "adverse_media_match": media.get("match", False),
        "document_verdict": dv.get("verdict"),
        "document_summary": dv.get("summary", ""),
        "verified_document_types": dv.get("verified_types", []),
        "document_type_mismatch": dv.get("document_type_mismatch", False),
    }


def build_executive_summary(state) -> str:
    """A concise investigation-ready paragraph built from existing findings."""
    ctx = build_case_context(state)
    name = ctx["customer_name"] or "The customer"
    decision = ctx["final_status"] or ctx["decision"]

    drivers = [d.get("factor") for d in (ctx["top_risk_drivers"] or [])][:3]
    parts: list[str] = [
        f"{name} received a {decision} decision with a risk score of {ctx['risk_score']}/100"
    ]
    if drivers:
        parts.append("driven primarily by " + ", ".join(drivers))
    summary = ", ".join(parts) + "."

    if ctx["edd_triggered"]:
        summary += " Enhanced Due Diligence was triggered"
        if ctx["edd_reasons"]:
            summary += " (" + "; ".join(ctx["edd_reasons"][:2]) + ")"
        summary += "."
    if ctx["consistency_issues"]:
        summary += f" Consistency analysis flagged {len(ctx['consistency_issues'])} issue(s)."
    if ctx["confidence"]:
        summary += f" Overall verification confidence is {round(ctx['confidence'] * 100)}%."
    return summary


# ── Deterministic answer handlers (Part 5) ──────────────────────────────────────

def _bullets(items: list[str]) -> str:
    return "\n".join(f"• {i}" for i in items if i)


def _decision_reason_answer(ctx: dict) -> str:
    reasons = [r for r in (ctx["decision_reasons"] or []) if isinstance(r, str)]
    decision = ctx["final_status"] or ctx["decision"]
    if not reasons:
        if ctx["explanation"]:
            return ctx["explanation"]
        return UNAVAILABLE
    return f"This customer was {decision} for the following reasons:\n{_bullets(reasons)}"


def _risk_score_answer(ctx: dict) -> str:
    contribs = ctx["risk_contributions"] or []
    if not contribs:
        return f"The risk score is {ctx['risk_score']}/100 ({ctx['risk_level']}). " + UNAVAILABLE
    lines = [f"{c.get('factor')} ({'+' if c.get('impact', 0) >= 0 else ''}{c.get('impact')})" for c in contribs]
    return (
        f"The risk score is {ctx['risk_score']}/100 ({ctx['risk_level']}). "
        f"It was built from these contributing factors:\n{_bullets(lines)}"
    )


def _top_drivers_answer(ctx: dict) -> str:
    drivers = ctx["top_risk_drivers"] or []
    if not drivers:
        return UNAVAILABLE
    lines = [f"{d.get('factor')} ({'+' if d.get('impact', 0) >= 0 else ''}{d.get('impact')})" for d in drivers]
    return "The top risk drivers were:\n" + _bullets(lines)


def _edd_answer(ctx: dict) -> str:
    if not ctx["edd_triggered"]:
        return "Enhanced Due Diligence was not triggered for this case."
    out = ""
    if ctx["edd_reasons"]:
        out += "Enhanced Due Diligence was triggered because:\n" + _bullets(ctx["edd_reasons"])
    if ctx["edd_findings"]:
        out += ("\n\n" if out else "") + "EDD review findings:\n" + _bullets(ctx["edd_findings"])
    return out or (ctx["edd_summary"] or UNAVAILABLE)


def _consistency_answer(ctx: dict) -> str:
    issues = ctx["consistency_issues"] or []
    if not issues:
        return "No cross-signal consistency issues were detected for this case."
    lines = [f"[{i.get('severity', 'low').upper()}] {i.get('description')}" for i in issues]
    return (
        f"Profile consistency score is {round((ctx['consistency_score'] or 1) * 100)}%. "
        f"The following issues were found:\n{_bullets(lines)}"
    )


def _documents_answer(ctx: dict) -> str:
    if ctx["verified_document_types"]:
        out = "Verified documents: " + ", ".join(ctx["verified_document_types"]) + "."
    elif ctx["document_summary"]:
        out = ctx["document_summary"]
    else:
        return UNAVAILABLE
    if ctx["document_type_mismatch"]:
        out += " Note: a document type mismatch was detected."
    return out


def _evidence_answer(ctx: dict) -> str:
    evidence: list[str] = []
    if ctx["sanctions_match"]:
        evidence.append("Sanctions watchlist match")
    if ctx["pep_match"]:
        evidence.append("PEP (politically exposed person) match")
    if ctx["adverse_media_match"]:
        evidence.append("Adverse media findings")
    if ctx["document_verdict"]:
        evidence.append(f"Document verification: {ctx['document_verdict']}")
    for d in (ctx["top_risk_drivers"] or [])[:3]:
        evidence.append(f"Risk factor: {d.get('factor')} ({'+' if d.get('impact', 0) >= 0 else ''}{d.get('impact')})")
    if not evidence:
        return UNAVAILABLE
    return "The decision is supported by the following evidence:\n" + _bullets(evidence)


# (keyword predicates, handler) — first match wins.
_ROUTES = [
    (lambda q: "summ" in q, lambda ctx: build_executive_summary_from_ctx(ctx)),
    (lambda q: ("edd" in q or "enhanced due diligence" in q), _edd_answer),
    (lambda q: ("consisten" in q or "inconsisten" in q or "contradict" in q), _consistency_answer),
    (lambda q: ("top" in q and "driver" in q), _top_drivers_answer),
    (lambda q: ("risk score" in q or "caused the risk" in q or "risk come" in q), _risk_score_answer),
    (lambda q: ("document" in q and ("verif" in q or "valid" in q)), _documents_answer),
    (lambda q: ("evidence" in q or "support" in q), _evidence_answer),
    (lambda q: ("why" in q and ("escalat" in q or "approv" in q or "review" in q or "decision" in q or "reject" in q)), _decision_reason_answer),
    (lambda q: ("why" in q or "reason" in q), _decision_reason_answer),
]


def build_executive_summary_from_ctx(ctx: dict) -> str:
    # Lightweight summary purely from ctx (avoids re-reading state).
    name = ctx["customer_name"] or "The customer"
    decision = ctx["final_status"] or ctx["decision"]
    drivers = [d.get("factor") for d in (ctx["top_risk_drivers"] or [])][:3]
    out = f"{name} received a {decision} decision (risk score {ctx['risk_score']}/100, {ctx['risk_level']})."
    if drivers:
        out += " Top risk drivers: " + ", ".join(drivers) + "."
    if ctx["edd_triggered"]:
        out += " Enhanced Due Diligence was triggered."
    if ctx["consistency_issues"]:
        out += f" {len(ctx['consistency_issues'])} consistency issue(s) flagged."
    if ctx["confidence"]:
        out += f" Verification confidence {round(ctx['confidence'] * 100)}%."
    return out


def answer_deterministic(ctx: dict, question: str) -> str | None:
    q = (question or "").lower().strip()
    if not q:
        return None
    for predicate, handler in _ROUTES:
        if predicate(q):
            return handler(ctx)
    return None


# ── Grounded LLM fallback (Part 6) ──────────────────────────────────────────────

def answer_with_llm(ctx: dict, question: str) -> str:
    from app.services.groq_client import groq_chat

    system = (
        "You are a compliance investigation copilot. Answer ONLY using the provided "
        "case context JSON. Do not invent facts, sanctions, PEP matches, or findings. "
        "Never change or override the official decision, risk score, or confidence. "
        "If the answer is not present in the context, reply exactly: "
        f"'{UNAVAILABLE}' Respond as JSON: {{\"answer\": \"...\"}}."
    )
    user = f"CASE CONTEXT:\n{json.dumps(ctx, default=str)}\n\nQUESTION: {question}"
    try:
        result = groq_chat(system, user, temperature=0.1)
    except Exception:  # noqa: BLE001 — copilot must never crash on LLM failure
        return UNAVAILABLE
    if result.get("fallback") or result.get("error"):
        return UNAVAILABLE
    answer = result.get("answer")
    return answer if isinstance(answer, str) and answer.strip() else UNAVAILABLE


def answer_question(state, question: str) -> dict[str, Any]:
    """Top-level entry: deterministic first, grounded LLM fallback otherwise."""
    ctx = build_case_context(state)
    deterministic = answer_deterministic(ctx, question)
    if deterministic is not None:
        return {"answer": deterministic, "source": "deterministic"}
    return {"answer": answer_with_llm(ctx, question), "source": "llm"}
