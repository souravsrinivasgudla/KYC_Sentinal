"""
Profile ↔ Document field verification.

Compares EVERY declared customer detail against the matching field extracted
from the uploaded proof document(s). Fields the document does not contain are
skipped. Any mismatch is reported so it can be surfaced to the user.

This complements the dedicated name / ID cross-checks by also covering date of
birth, nationality, etc., and by producing a single structured list of
field-by-field results for display.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.services.id_cross_check import ids_equivalent
from app.services.name_cross_check import names_equivalent

POI_DOC_TYPES = {"aadhaar_card", "pan_card", "passport", "voter_id", "driving_licence"}

_NULLISH = {"", "null", "none", "n/a", "na", "not available", "not found"}


def _clean(value: Any) -> str:
    s = str(value or "").strip()
    return "" if s.lower() in _NULLISH else s


def _merge_doc_fields(document_verdict: dict[str, Any]) -> dict[str, str]:
    """Merge extracted fields across all ID documents (first non-empty wins)."""
    merged: dict[str, str] = {}
    for doc in document_verdict.get("per_document", []):
        if doc.get("doc_type") not in POI_DOC_TYPES:
            continue
        gf = doc.get("groq_extracted_fields") or {}
        qr = doc.get("qr_scan_result") or {}
        sources = {
            "full_name":       gf.get("full_name") or qr.get("qr_full_name"),
            "date_of_birth":   gf.get("date_of_birth") or qr.get("qr_date_of_birth"),
            "document_number": doc.get("doc_number") or gf.get("document_number") or qr.get("qr_document_number"),
            "nationality":     gf.get("nationality"),
            "gender":          gf.get("gender"),
        }
        for key, val in sources.items():
            if key not in merged and _clean(val):
                merged[key] = _clean(val)
    return merged


# ── Field comparators ──────────────────────────────────────────────────────────

def _parse_date(value: str) -> Optional[tuple[int, Optional[int], Optional[int]]]:
    """Return (year, month, day) — month/day may be None for year-only values."""
    s = _clean(value)
    if not s:
        return None
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)        # YYYY-MM-DD
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)        # DD/MM/YYYY
    if m:
        return (int(m.group(3)), int(m.group(2)), int(m.group(1)))
    ym = re.search(r"(?:19|20)\d{2}", s)                          # year only
    if ym:
        return (int(ym.group(0)), None, None)
    return None


def _dob_match(declared: str, extracted: str) -> Optional[bool]:
    """Match DOBs. Year-only documents (e.g. Aadhaar) match on year alone."""
    pd, px = _parse_date(declared), _parse_date(extracted)
    if not pd or not px:
        return None  # cannot compare
    if pd[0] != px[0]:
        return False  # year differs → mismatch
    if pd[1] and pd[2] and px[1] and px[2]:
        return pd[1] == px[1] and pd[2] == px[2]
    return True  # one side is year-only → accept matching year


def _nationality_match(declared: str, extracted: str) -> Optional[bool]:
    """Lenient nationality match (India ↔ Indian). Conservative to avoid false flags."""
    d = re.sub(r"[^a-z]", "", _clean(declared).lower())
    x = re.sub(r"[^a-z]", "", _clean(extracted).lower())
    if not d or not x or len(d) < 4 or len(x) < 4:
        return None  # too short / a code → can't compare reliably
    if d == x or d.startswith(x[:4]) or x.startswith(d[:4]):
        return True
    return False


FIELD_LABELS = {
    "name": "Name",
    "dob": "Date of Birth",
    "id_number": "ID / Document Number",
    "nationality": "Nationality",
}


def verify_profile_against_document(
    customer_profile: dict[str, Any],
    document_verdict: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Returns:
      {
        "checks": [{"field","label","declared","extracted","match"}],  # only fields the doc has
        "mismatches": [...subset where match is False...],
        "has_mismatch": bool,
        "note": "<human-readable summary or ''>",
      }
    """
    empty = {"checks": [], "mismatches": [], "has_mismatch": False, "note": ""}
    if not document_verdict:
        return empty

    doc = _merge_doc_fields(document_verdict)
    if not doc:
        return empty

    checks: list[dict[str, Any]] = []

    def _add(field: str, declared: str, extracted: str, match: Optional[bool]) -> None:
        if match is None:
            return
        checks.append({
            "field": field,
            "label": FIELD_LABELS.get(field, field),
            "declared": declared,
            "extracted": extracted,
            "match": bool(match),
        })

    declared_name = _clean(customer_profile.get("name"))
    if doc.get("full_name") and declared_name:
        _add("name", declared_name, doc["full_name"], names_equivalent(declared_name, doc["full_name"]))

    declared_dob = _clean(customer_profile.get("dob"))
    if doc.get("date_of_birth") and declared_dob:
        _add("dob", declared_dob, doc["date_of_birth"], _dob_match(declared_dob, doc["date_of_birth"]))

    declared_id = _clean(customer_profile.get("id_number"))
    if doc.get("document_number") and declared_id:
        _add("id_number", declared_id, doc["document_number"], ids_equivalent(declared_id, doc["document_number"]))

    declared_nat = _clean(customer_profile.get("nationality_normalized") or customer_profile.get("nationality"))
    if doc.get("nationality") and declared_nat:
        _add("nationality", declared_nat, doc["nationality"], _nationality_match(declared_nat, doc["nationality"]))

    mismatches = [c for c in checks if c["match"] is False]
    note = ""
    if mismatches:
        parts = [f"{c['label']} (entered '{c['declared']}' vs document '{c['extracted']}')" for c in mismatches]
        note = "Details on the document do not match what was entered: " + "; ".join(parts) + "."

    return {
        "checks": checks,
        "mismatches": mismatches,
        "has_mismatch": bool(mismatches),
        "note": note,
    }
