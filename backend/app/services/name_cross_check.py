"""Cross-check declared customer name against names on uploaded driving licences."""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

NAME_LABEL_PATTERNS = [
    re.compile(r"name\s*[:\-]?\s*([A-Za-z][A-Za-z\s.'\-]{2,80})", re.IGNORECASE),
    re.compile(r"holder(?:'s)?\s*name\s*[:\-]?\s*([A-Za-z][A-Za-z\s.'\-]{2,80})", re.IGNORECASE),
    re.compile(r"licen[cs]ee\s*name\s*[:\-]?\s*([A-Za-z][A-Za-z\s.'\-]{2,80})", re.IGNORECASE),
]

_NAME_VALUE_STOP = re.compile(
    r"\b(son|daughter|wife|husband|father|mother|dob|date|address|blood|valid|dl|licen)\b",
    re.IGNORECASE,
)

MATCH_THRESHOLD = 85


def normalize_name(value: str) -> str:
    """Normalize a person name for comparison."""
    v = re.sub(r"[^A-Za-z\s.'\-]", " ", value or "")
    v = re.sub(r"\s+", " ", v).strip().upper()
    return v


def names_equivalent(declared: str, extracted: str, threshold: int = MATCH_THRESHOLD) -> bool:
    """True when declared name matches document name (fuzzy token sort)."""
    a = normalize_name(declared)
    b = normalize_name(extracted)
    if not a or not b:
        return False
    if a == b:
        return True
    if fuzz.token_sort_ratio(a, b) >= threshold:
        return True
    # Require at least two significant tokens to overlap (handles partial OCR)
    a_parts = {p for p in a.split() if len(p) > 2}
    b_parts = {p for p in b.split() if len(p) > 2}
    if len(a_parts) >= 2 and len(a_parts & b_parts) >= 2:
        return True
    if len(a_parts) == 1 and len(b_parts) == 1 and next(iter(a_parts)) == next(iter(b_parts)):
        return True
    return False


def _trim_name_capture(raw: str) -> str:
    trimmed = _NAME_VALUE_STOP.split(raw, maxsplit=1)[0].strip()
    return trimmed or raw.strip()


def extract_name_from_dl_text(text: str) -> str:
    """Extract holder name from driving licence text, preferring labelled fields."""
    if not text:
        return ""
    for pat in NAME_LABEL_PATTERNS:
        m = pat.search(text)
        if m:
            name = _trim_name_capture(m.group(1))
            if len(normalize_name(name)) >= 3:
                return name.strip().upper()
    return ""


def _document_name_candidates(doc: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    if doc.get("name_from_document"):
        candidates.append(str(doc["name_from_document"]))
    gf = doc.get("groq_extracted_fields") or {}
    full_name = gf.get("full_name")
    if full_name and str(full_name).strip().lower() not in ("", "null", "none"):
        candidates.append(str(full_name))
    text_name = extract_name_from_dl_text(doc.get("text_content", "") or "")
    if text_name:
        candidates.append(text_name)
    return candidates


def find_declared_name_in_text(declared: str, text: str) -> str:
    """Return document name when declared name appears in licence text."""
    if not declared or not text:
        return ""
    declared_norm = normalize_name(declared)
    if not declared_norm:
        return ""
    text_norm = normalize_name(text)
    if declared_norm in text_norm:
        extracted = extract_name_from_dl_text(text)
        return extracted or declared.strip().upper()
    for part in declared_norm.split():
        if len(part) > 2 and part not in text_norm:
            return ""
    extracted = extract_name_from_dl_text(text)
    if extracted and names_equivalent(declared, extracted):
        return extracted
    return ""


def _name_matches_document(declared: str, doc: dict[str, Any]) -> bool:
    pm = doc.get("groq_profile_match") or {}
    if pm.get("name_matches") is True:
        return True

    text = doc.get("text_content", "") or ""
    if find_declared_name_in_text(declared, text):
        return True

    for candidate in _document_name_candidates(doc):
        if names_equivalent(declared, candidate):
            return True
    return False


def check_name_mismatch(
    declared_name: str,
    document_verdict: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Compare declared name with names on driving licence documents.
    Returns mismatch dict or None if no mismatch / cannot compare.
    """
    declared = normalize_name(declared_name)
    if not declared:
        return None
    if not document_verdict:
        return None

    dl_docs = [
        doc for doc in document_verdict.get("per_document", [])
        if doc.get("doc_type") == "driving_licence"
    ]
    if not dl_docs:
        return None

    if any(_name_matches_document(declared_name, doc) for doc in dl_docs):
        return None

    extracted_display = ""
    for doc in dl_docs:
        for candidate in _document_name_candidates(doc):
            if normalize_name(candidate):
                extracted_display = candidate.strip()
                break
        if extracted_display:
            break

    if not extracted_display:
        return None

    declared_display = declared_name.strip()

    return {
        "declared": declared_display,
        "extracted": extracted_display,
        "reason": (
            f"Name entered ({declared_display}) does not match the name "
            f"on the driving licence ({extracted_display})."
        ),
        "short_reason": "Entered name does not match the name on the driving licence.",
        "severity": "critical",
    }
