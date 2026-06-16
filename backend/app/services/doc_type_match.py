"""
Document-type consistency check.

Compares the document type the customer DECLARED on the intake form against
the type the classifier DETECTED from the uploaded document(s). A mismatch
(e.g. declared "PAN Card" but the upload is an Aadhaar Card) is a fraud /
evidence-to-claim signal that feeds risk scoring, explainability, and audit.
"""

from __future__ import annotations

from typing import Any

# Declared label (lower-cased) → classifier doc_type key
DECLARED_TO_KEY: dict[str, str] = {
    "aadhaar card": "aadhaar_card",
    "aadhaar": "aadhaar_card",
    "pan card": "pan_card",
    "pan": "pan_card",
    "passport": "passport",
    "voter id": "voter_id",
    "voter id (epic)": "voter_id",
    "driving licence": "driving_licence",
    "driving license": "driving_licence",
}

# Classifier doc_type key → display label
KEY_TO_DISPLAY: dict[str, str] = {
    "aadhaar_card": "Aadhaar Card",
    "pan_card": "PAN Card",
    "passport": "Passport",
    "voter_id": "Voter ID",
    "driving_licence": "Driving Licence",
    "unknown": "Unrecognised Document",
}


def _empty_result(declared: str, comparable: bool = False) -> dict[str, Any]:
    return {
        "declared_doc_type": declared,
        "detected_doc_type": "",
        "document_type_mismatch": False,
        "mismatch_severity": "NONE",
        "points": 0,
        "reason": "",
        "short_reason": "",
        "comparable": comparable,
        "detected_confidence": 0.0,
    }


def check_doc_type_mismatch(
    declared_doc_type: str,
    per_document: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare the declared document type against the detected type(s).

    Returns a dict that is ALWAYS populated (even when types match or the
    declared type is not comparable), so callers can store a consistent record:

        declared_doc_type, detected_doc_type, document_type_mismatch,
        mismatch_severity (NONE|LOW|MEDIUM|HIGH), points, reason, short_reason.

    Severity / risk points scale with classifier confidence in the *different*
    detected type: <0.70 → LOW (+15), 0.70-0.85 → MEDIUM (+20), ≥0.85 → HIGH (+25).
    """
    declared = (declared_doc_type or "").strip()
    declared_key = DECLARED_TO_KEY.get(declared.lower())

    # Not comparable: no declared type, a custom/"Other" type, or a type the
    # classifier does not cover (National ID / Residence Permit).
    if not per_document or not declared_key:
        return _empty_result(declared, comparable=bool(declared_key))

    result = _empty_result(declared, comparable=True)

    detected_keys = {d.get("doc_type") for d in per_document}
    if declared_key in detected_keys:
        match_doc = next(d for d in per_document if d.get("doc_type") == declared_key)
        result["detected_doc_type"] = (
            match_doc.get("doc_type_display") or KEY_TO_DISPLAY.get(declared_key, declared)
        )
        return result

    # Mismatch — pick the primary detected doc (highest type confidence,
    # preferring a recognised type over "unknown").
    known = [d for d in per_document if d.get("doc_type") and d.get("doc_type") != "unknown"]
    pool = known or per_document
    primary = max(pool, key=lambda d: d.get("doc_type_confidence", 0.0))

    detected_display = (
        primary.get("doc_type_display")
        or KEY_TO_DISPLAY.get(primary.get("doc_type", ""), primary.get("doc_type", "") or "Unknown")
    )
    conf = float(primary.get("doc_type_confidence", 0.0))

    if conf >= 0.85:
        severity, points = "HIGH", 25
    elif conf >= 0.70:
        severity, points = "MEDIUM", 20
    else:
        severity, points = "LOW", 15

    result.update({
        "detected_doc_type": detected_display,
        "document_type_mismatch": True,
        "mismatch_severity": severity,
        "points": points,
        "detected_confidence": round(conf, 4),
        "reason": (
            f"The uploaded document was identified as {detected_display} "
            f"while the customer declared {declared}."
        ),
        "short_reason": f"Declared {declared} but document is {detected_display}",
    })
    return result
