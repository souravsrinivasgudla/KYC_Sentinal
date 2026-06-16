"""
Enhanced Due Diligence Agent (Phase 4).

Performs a deeper review of findings ALREADY produced by upstream agents. It
calls no external services and invents no data — it synthesises the existing
screening, entity-resolution, adverse-media, evidence, document, and risk-
contribution outputs into concrete EDD findings.

Runs only when EDD has been triggered.
"""

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.risk_breakdown import generate_risk_breakdown


def enhanced_due_diligence_agent(state: KYCState) -> KYCState:
    findings: list[str] = []

    # ── Compliance screening ──────────────────────────────────────────────────
    screening = state.screening_results or {}
    pep_hits = screening.get("pep_hits", []) or []
    sanctions_hits = screening.get("sanctions_hits", []) or []
    if screening.get("pep"):
        n = len(pep_hits)
        findings.append(
            f"Potential PEP association detected ({n} watchlist match{'es' if n != 1 else ''})."
        )
    if screening.get("sanctions"):
        n = len(sanctions_hits)
        findings.append(
            f"Sanctions list match requires manual confirmation ({n} hit{'s' if n != 1 else ''})."
        )

    # ── Entity resolution ─────────────────────────────────────────────────────
    er = state.entity_resolution or {}
    matches = er.get("matches", []) or []
    if matches and not er.get("is_unique_entity", True):
        findings.append(
            f"Customer could not be uniquely resolved against watchlists "
            f"({len(matches)} potential identity match(es))."
        )

    # ── Adverse media ─────────────────────────────────────────────────────────
    am = state.adverse_media or {}
    if am.get("match"):
        findings.append(
            f"Adverse media identified ({am.get('article_count', 0)} item(s), "
            f"{am.get('severity', 'Unknown')} severity)."
        )

    # ── Document verification ─────────────────────────────────────────────────
    dv = state.document_verdict or {}
    if dv.get("document_type_mismatch"):
        findings.append(
            f"Document type inconsistency: declared "
            f"{dv.get('declared_doc_type') or 'unknown'} vs detected "
            f"{dv.get('detected_doc_type') or 'unknown'}."
        )
    if dv.get("id_mismatch"):
        findings.append("Declared ID number does not match the uploaded document.")
    if dv.get("verdict") == "NEEDS_REVIEW":
        findings.append("Document verification returned NEEDS_REVIEW — manual inspection advised.")

    # ── Evidence validation ───────────────────────────────────────────────────
    ev = state.evidence_validation or {}
    if ev and ev.get("validation_passed") is False:
        findings.append("Document evidence did not fully pass semantic validation.")

    # ── Jurisdiction / occupation risk (from existing risk contributions) ─────
    contributions = generate_risk_breakdown(state.risk_assessment.get("breakdown", []))
    if any(c.get("category") == "country" for c in contributions):
        findings.append("Customer exhibits elevated jurisdiction (country) risk.")
    if any(c.get("category") == "occupation" for c in contributions):
        findings.append("Customer occupation carries an elevated risk profile.")
    if any(c.get("category") == "funds" for c in contributions):
        findings.append("Source of funds is missing or could not be corroborated.")

    if not findings:
        findings.append(
            "No additional adverse findings beyond the triggering risk indicators; "
            "elevated risk score warrants senior review."
        )

    state.edd_findings = findings
    state.workflow_path.append("enhanced_due_diligence")
    log_event(
        state,
        "Enhanced Due Diligence Agent",
        f"Enhanced review produced {len(findings)} finding(s).",
        {"findings": findings},
    )
    return state
