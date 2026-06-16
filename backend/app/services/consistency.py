"""
Cross-signal consistency analysis (Phase 5).

A rule-based engine that checks whether a customer's *story* is internally
coherent — comparing declarations, extracted document fields, and verification
results to surface contradictions. It uses ONLY data already produced by the
pipeline, invents nothing, and is purely advisory: it never changes risk,
confidence, EDD triggers, or the decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Severity → consistency-score penalty (Part 3).
_SEVERITY_PENALTY = {"low": 0.10, "medium": 0.25, "high": 0.40}
_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _age_from_dob(dob: str) -> Optional[int]:
    if not dob:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            d = datetime.strptime(dob.strip(), fmt)
        except ValueError:
            continue
        today = datetime.now(timezone.utc)
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return None


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().replace(",", " ").split() if len(t) > 2}


# ── Rule sets ───────────────────────────────────────────────────────────────────

def _rule_occupation_income(profile: dict, issues: list[dict]) -> None:
    """RULE SET A — occupation vs source of funds."""
    occ = (profile.get("occupation_normalized") or profile.get("occupation", "")).lower()
    funds_raw = (profile.get("source_of_funds", "") or "").strip()
    funds = funds_raw.lower()
    if not occ or not funds:
        return
    business_like = any(k in funds for k in ("business", "corporate", "revenue", "investment"))
    if "student" in occ and business_like:
        issues.append({
            "type": "occupation_income_mismatch", "severity": "medium",
            "description": f"Student profile reports '{funds_raw}' as source of funds.",
        })
    elif "unemployed" in occ and any(k in funds for k in ("business", "corporate", "revenue", "salary")):
        issues.append({
            "type": "occupation_income_mismatch", "severity": "medium",
            "description": f"Unemployed individual declared '{funds_raw}' as source of funds.",
        })


def _rule_nationality_document(profile: dict, document_verdict: dict, issues: list[dict]) -> None:
    """RULE SET B — declared nationality vs document signals (only if evidence exists)."""
    declared = (profile.get("nationality_normalized") or profile.get("nationality", "")).strip()
    if not declared:
        return
    declared_tokens = _tokens(declared)
    per_doc = (document_verdict or {}).get("per_document") or []
    for doc in per_doc:
        fields = doc.get("groq_extracted_fields") or {}
        for key in ("nationality", "country", "issuing_country", "country_of_issue", "issuing_state"):
            val = fields.get(key)
            if not isinstance(val, str) or not val.strip():
                continue
            doc_tokens = _tokens(val)
            if doc_tokens and declared_tokens and not (doc_tokens & declared_tokens):
                issues.append({
                    "type": "nationality_document_mismatch", "severity": "high",
                    "description": f"Declared nationality '{declared}' differs from document evidence ('{val.strip()}').",
                })
                return  # one finding is enough


def _rule_age_occupation(profile: dict, issues: list[dict]) -> None:
    """RULE SET C — age vs occupation (conservative)."""
    age = _age_from_dob(profile.get("dob_normalized") or profile.get("dob", ""))
    if age is None:
        return
    occ = (profile.get("occupation_normalized") or profile.get("occupation", "")).lower()
    if not occ:
        return
    if age < 21 and "retired" in occ:
        issues.append({
            "type": "age_occupation_mismatch", "severity": "high",
            "description": f"Customer aged {age} declared occupation 'retired'.",
        })
    elif age < 18 and any(k in occ for k in ("executive", "director", "ceo", "chief", "manager", "president")):
        issues.append({
            "type": "age_occupation_mismatch", "severity": "high",
            "description": f"Customer aged {age} declared a senior executive occupation.",
        })
    elif age > 80 and "student" in occ:
        issues.append({
            "type": "age_occupation_mismatch", "severity": "medium",
            "description": f"Customer aged {age} declared occupation 'student'.",
        })


def _rule_document_type(document_verdict: dict, issues: list[dict]) -> None:
    """RULE SET D — document type contradiction (surface as a consistency finding)."""
    dv = document_verdict or {}
    if not dv.get("document_type_mismatch"):
        return
    severity = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}.get(dv.get("mismatch_severity"), "medium")
    issues.append({
        "type": "document_type_contradiction", "severity": severity,
        "description": (
            f"Declared document type '{dv.get('declared_doc_type') or 'unknown'}' but the uploaded "
            f"document was detected as '{dv.get('detected_doc_type') or 'unknown'}'."
        ),
    })


def _rule_missing_critical(profile: dict, risk_score: float, edd_triggered: bool, issues: list[dict]) -> None:
    """RULE SET E — missing critical information on a high-risk profile."""
    high_risk = (risk_score or 0) >= 70 or bool(edd_triggered)
    if not high_risk:
        return
    if not (profile.get("source_of_funds", "") or "").strip():
        issues.append({
            "type": "critical_information_gap", "severity": "medium",
            "description": "High-risk profile is missing source of funds.",
        })
    if not (profile.get("id_number", "") or "").strip():
        issues.append({
            "type": "critical_information_gap", "severity": "medium",
            "description": "High-risk profile is missing an ID / document number.",
        })


def detect_consistency_issues(state) -> list[dict[str, Any]]:
    """Run all rule sets against the current state and return sorted issues (severity desc)."""
    profile = state.customer_profile or {}
    document_verdict = state.document_verdict or {}
    risk_score = (state.risk_assessment or {}).get("risk_score", 0)

    issues: list[dict[str, Any]] = []
    _rule_occupation_income(profile, issues)
    _rule_nationality_document(profile, document_verdict, issues)
    _rule_age_occupation(profile, issues)
    _rule_document_type(document_verdict, issues)
    _rule_missing_critical(profile, risk_score, state.edd_triggered, issues)

    issues.sort(key=lambda i: _SEVERITY_RANK.get(i.get("severity", "low"), 0), reverse=True)
    return issues


def calculate_consistency_score(issues: list[dict[str, Any]]) -> float:
    """1.0 = fully consistent, 0.0 = highly inconsistent. Informational only."""
    score = 1.0
    for issue in issues:
        score -= _SEVERITY_PENALTY.get(issue.get("severity", "low"), 0.10)
    return round(max(0.0, min(1.0, score)), 4)


def build_consistency_summary(issues: list[dict[str, Any]], score: float) -> str:
    if not issues:
        return "Profile is internally consistent; no cross-signal contradictions were detected."

    highest = max(issues, key=lambda i: _SEVERITY_RANK.get(i.get("severity", "low"), 0))
    level = {"high": "significant", "medium": "moderate", "low": "minor"}[highest.get("severity", "low")]

    topics = {
        "occupation_income_mismatch": "occupation and source of funds",
        "nationality_document_mismatch": "declared nationality and document evidence",
        "age_occupation_mismatch": "age and occupation",
        "document_type_contradiction": "declared and detected document type",
        "critical_information_gap": "missing critical information",
    }
    seen: list[str] = []
    for issue in issues:
        t = topics.get(issue.get("type"), "profile attributes")
        if t not in seen:
            seen.append(t)
    topic_text = "; ".join(seen[:3])
    return (
        f"Profile consistency analysis identified {level} discrepancies involving {topic_text}."
    )
