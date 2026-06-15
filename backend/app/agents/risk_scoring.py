"""
Risk Scoring Agent
==================
Combines:
  1. Rule-based weighted signals (explainability / audit trail)
  2. XGBoost ML model prediction (trained on KYC dataset)

Final score = 0.45 * rule_score + 0.55 * ml_score
If ML model is unavailable, falls back to 100% rule-based.
"""

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.xgboost_scorer import predict_risk

RISK_WEIGHTS = {
    "sanctions_match": 50,
    "pep_match": 25,
    "adverse_media_high": 30,
    "adverse_media_medium": 15,
    "missing_funds": 15,
    "occupation_risk": 20,
    "country_risk": 10,
}

# Blend weights: how much each source contributes
ML_BLEND_WEIGHT = 0.55
RULE_BLEND_WEIGHT = 0.45


def _rule_based_score(state: KYCState) -> tuple[int, list[dict]]:
    """Compute rule-based risk score and breakdown."""
    screening = state.screening_results
    media = state.adverse_media
    financial = state.financial_profile

    breakdown: list[dict] = []
    total = 0

    if screening.get("sanctions"):
        pts = RISK_WEIGHTS["sanctions_match"]
        total += pts
        breakdown.append({"signal": "Sanctions Match", "points": pts, "source": "rule"})

    if screening.get("pep"):
        pts = RISK_WEIGHTS["pep_match"]
        total += pts
        breakdown.append({"signal": "PEP Match", "points": pts, "source": "rule"})

    if media.get("match"):
        severity = media.get("severity", "Medium")
        if severity == "High":
            pts = RISK_WEIGHTS["adverse_media_high"]
        elif severity == "Medium":
            pts = RISK_WEIGHTS["adverse_media_medium"]
        else:
            pts = 5
        total += pts
        breakdown.append({"signal": f"Adverse Media ({severity})", "points": pts, "source": "rule"})

    if financial.get("missing_source_of_funds"):
        pts = RISK_WEIGHTS["missing_funds"]
        total += pts
        breakdown.append({"signal": "Missing Source of Funds", "points": pts, "source": "rule"})

    occ_score = financial.get("occupation_risk_score", 0)
    if occ_score >= 20:
        pts = RISK_WEIGHTS["occupation_risk"]
        total += pts
        breakdown.append({"signal": "High-Risk Occupation", "points": pts, "source": "rule"})

    country_score = financial.get("country_risk_score", 0)
    if country_score >= 15:
        pts = RISK_WEIGHTS["country_risk"]
        total += pts
        breakdown.append({"signal": "Elevated Country Risk", "points": pts, "source": "rule"})

    evidence = state.evidence_validation
    if not state.uploaded_evidence:
        pts = 20
        total += pts
        breakdown.append({"signal": "No Proof Documents Uploaded", "points": pts, "source": "rule"})
    elif not evidence.get("validation_passed"):
        pts = 25
        total += pts
        breakdown.append({"signal": "Document Evidence Failed Validation", "points": pts, "source": "rule"})

    groq_flags = state.groq_verification.get("risk_flags", [])
    if groq_flags:
        pts = min(len(groq_flags) * 5, 15)
        total += pts
        breakdown.append({"signal": f"Groq AI Risk Flags ({len(groq_flags)})", "points": pts, "source": "rule"})

    # ID number vs document cross-check
    id_mismatch = state.document_verdict.get("id_mismatch")
    if not id_mismatch:
        from app.services.id_cross_check import check_id_mismatch
        id_mismatch = check_id_mismatch(
            state.customer_profile.get("id_number", ""),
            state.document_verdict,
        )
    if id_mismatch:
        pts = 35
        total += pts
        breakdown.append({
            "signal": "ID Number Mismatch",
            "points": pts,
            "source": "id_cross_check",
            "detail": id_mismatch.get("short_reason", ""),
        })

    # Declared vs detected document-type mismatch
    doc_type_match = state.document_verdict.get("doc_type_match")
    if doc_type_match and doc_type_match.get("document_type_mismatch"):
        pts = doc_type_match.get("points", 15)
        total += pts
        breakdown.append({
            "signal": "Document Type Inconsistency",
            "points": pts,
            "source": "doc_type_check",
            "detail": doc_type_match.get("short_reason", ""),
        })

    return min(total, 100), breakdown


def risk_scoring_agent(state: KYCState) -> KYCState:
    # ── Rule-based score ────────────────────────────────────────────────────
    rule_score, breakdown = _rule_based_score(state)

    # ── XGBoost ML prediction ───────────────────────────────────────────────
    ml_result = predict_risk(
        screening_results=state.screening_results,
        financial_profile=state.financial_profile,
        customer_profile=state.customer_profile,
        adverse_media=state.adverse_media,
        evidence_validation=state.evidence_validation,
        uploaded_evidence=state.uploaded_evidence,
        groq_verification=state.groq_verification,
    )

    # ── Blend scores ────────────────────────────────────────────────────────
    if ml_result.get("ml_used"):
        ml_score = ml_result["ml_risk_score"]
        total = int(round(RULE_BLEND_WEIGHT * rule_score + ML_BLEND_WEIGHT * ml_score))
        total = max(0, min(100, total))

        # Add ML result to breakdown
        breakdown.append({
            "signal": f"XGBoost ML Model ({ml_result['ml_risk_level']}, {int(ml_result['ml_confidence'] * 100)}% confidence)",
            "points": ml_score,
            "source": "ml",
            "ml_class": ml_result["ml_risk_level"],
        })
        scoring_method = "hybrid"
    else:
        total = rule_score
        scoring_method = "rule_based"

    # ── Risk level thresholds ───────────────────────────────────────────────
    if total >= 70:
        risk_level = "High"
    elif total >= 40:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    state.risk_assessment = {
        "risk_score": total,
        "risk_level": risk_level,
        "breakdown": breakdown,
        "weights_used": RISK_WEIGHTS,
        "scoring_method": scoring_method,
        "rule_score": rule_score,
        **({"ml_result": ml_result} if ml_result.get("ml_used") else {}),
    }
    state.workflow_path.append("risk_scoring")
    log_event(
        state,
        "Risk Scoring Agent",
        f"Risk score: {total} ({risk_level}) [{scoring_method}]",
        {"breakdown": breakdown, "rule_score": rule_score, "ml_score": ml_result.get("ml_risk_score")},
    )
    return state
