"""Cross-check declared ID number against numbers extracted from uploaded documents."""

from __future__ import annotations

import re
from typing import Any

# Compact Indian DL (e.g. AP43720240003089, TN0120190012345)
COMPACT_DL = re.compile(r"\b([A-Z]{2}\d{11,17})\b", re.IGNORECASE)

# Indian driving licence number with optional separators
DL_NUMBER_CORE = re.compile(
    r"\b([A-Z]{2}[-\s]?\d{1,2}[-\s/]?\d{2,4}[-\s/]?\d{4,11})\b",
    re.IGNORECASE,
)

DL_LABEL_PATTERNS = [
    re.compile(r"dl\s*no\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\s\-/]{4,32})", re.IGNORECASE),
    re.compile(r"licen[cs]e\s*no\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\s\-/]{4,32})", re.IGNORECASE),
    re.compile(r"dl\s*number\s*[:\-]?\s*([A-Z0-9][A-Z0-9\s\-/]{4,32})", re.IGNORECASE),
    re.compile(r"driving\s*licen[cs]e\s*no\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\s\-/]{4,32})", re.IGNORECASE),
]

# OCR often misreads "Date OF" / "Valid Till" as a DL number like "OF 29-11-2024"
DATE_FRAGMENT = re.compile(
    r"^[A-Z]{2}[\s\-/]+\d{1,2}[\s\-/]+\d{1,2}[\s\-/]+\d{2,4}$",
    re.IGNORECASE,
)

# Two-letter tokens that are English words, not Indian state codes
FALSE_DL_PREFIXES = frozenset({
    "OF", "ON", "TO", "IN", "AT", "OR", "IF", "NO", "BY", "AS", "IS", "IT",
    "DO", "DT", "UP", "MY", "WE", "HE", "ME", "US", "AN", "AM", "PM",
})

_LABEL_VALUE_STOP = re.compile(
    r"\b(valid|till|issue|issued|date|expir|birth|name|address|blood)\b",
    re.IGNORECASE,
)


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_dl_id(value: str) -> str:
    """Strip separators so TN-01-2019-1234567 matches TN0120191234567."""
    return re.sub(r"[\s\-/]", "", (value or "").upper())


def is_dl_format(value: str) -> bool:
    compact = normalize_dl_id(value)
    return bool(compact) and bool(re.match(r"^[A-Z]{2}\d", compact))


def is_plausible_dl_number(value: str) -> bool:
    """Reject date fragments and other OCR false positives."""
    if not value or not str(value).strip():
        return False
    v = str(value).strip().upper()
    if DATE_FRAGMENT.match(v):
        return False
    compact = normalize_dl_id(v)
    if not re.match(r"^[A-Z]{2}\d", compact):
        return False
    prefix = compact[:2]
    digit_count = len(_digits_only(compact))
    if digit_count < 10:
        return False
    if prefix in FALSE_DL_PREFIXES and digit_count <= 8:
        return False
    if COMPACT_DL.fullmatch(compact):
        return True
    if DL_NUMBER_CORE.fullmatch(v) and prefix not in FALSE_DL_PREFIXES:
        return digit_count >= 10
    return digit_count >= 11 and prefix not in FALSE_DL_PREFIXES


def find_declared_dl_in_text(declared: str, text: str) -> str:
    """Return the DL number from text when it matches the declared id_number."""
    if not declared or not text:
        return ""
    target = normalize_dl_id(declared)
    if not target or not is_dl_format(declared):
        return ""

    text_upper = text.upper()
    if target in normalize_dl_id(text_upper):
        for m in COMPACT_DL.finditer(text_upper):
            if ids_equivalent(declared, m.group(1)):
                return m.group(1).strip().upper()
        for m in DL_NUMBER_CORE.finditer(text_upper):
            if ids_equivalent(declared, m.group(1)) and is_plausible_dl_number(m.group(1)):
                return m.group(1).strip().upper()
        return declared.strip().upper()

    for m in COMPACT_DL.finditer(text_upper):
        if ids_equivalent(declared, m.group(1)):
            return m.group(1).strip().upper()
    for m in DL_NUMBER_CORE.finditer(text_upper):
        if ids_equivalent(declared, m.group(1)) and is_plausible_dl_number(m.group(1)):
            return m.group(1).strip().upper()
    return ""


def _trim_label_capture(raw: str) -> str:
    """Keep only the value beside DL No, stopping at the next field label."""
    trimmed = _LABEL_VALUE_STOP.split(raw, maxsplit=1)[0].strip()
    return trimmed or raw.strip()


def _dl_candidates_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    if not text:
        return candidates

    for pat in DL_LABEL_PATTERNS:
        for m in pat.finditer(text):
            raw = _trim_label_capture(m.group(1))
            for cm in COMPACT_DL.finditer(raw):
                candidates.append(cm.group(1))
            dm = DL_NUMBER_CORE.search(raw)
            if dm:
                candidates.append(dm.group(1))
            first_token = raw.split()[0] if raw.split() else ""
            if first_token and is_dl_format(first_token):
                candidates.append(first_token)

    for m in COMPACT_DL.finditer(text):
        candidates.append(m.group(1))
    for m in DL_NUMBER_CORE.finditer(text):
        candidates.append(m.group(1))

    return candidates


def extract_dl_number_from_text(text: str, declared_id: str = "") -> str:
    """
    Extract driving licence number, preferring the value beside 'DL No' / 'Licence No'.
    When declared_id is provided, match it against text first.
    """
    if not text and not declared_id:
        return ""

    if declared_id:
        found = find_declared_dl_in_text(declared_id, text)
        if found:
            return found

    plausible = [
        c.strip().upper()
        for c in _dl_candidates_from_text(text)
        if is_plausible_dl_number(c)
    ]
    if not plausible:
        return ""

    return max(
        plausible,
        key=lambda c: (len(normalize_dl_id(c)), len(c)),
    )


def normalize_id(value: str) -> str:
    """Normalize ID for comparison (Aadhaar digits-only, DL/PAN alphanumeric, account digits)."""
    v = (value or "").strip().upper()
    if not v:
        return ""
    from app.services.account_cross_check import is_account_format, normalize_account_number
    if is_account_format(v):
        return normalize_account_number(v)
    digits = _digits_only(v)
    if len(digits) == 12 and re.fullmatch(r"\d{12}", digits):
        return digits
    if is_dl_format(v):
        return normalize_dl_id(v)
    return re.sub(r"[\s\-/]", "", v)


def ids_equivalent(declared: str, extracted: str) -> bool:
    """True when declared id_number matches document number (DL/account-aware)."""
    if not declared or not extracted:
        return False
    from app.services.account_cross_check import accounts_equivalent, is_account_format

    if is_account_format(declared) or is_account_format(extracted):
        return accounts_equivalent(declared, extracted)
    if normalize_id(declared) == normalize_id(extracted):
        return True
    if is_dl_format(declared) or is_dl_format(extracted):
        return normalize_dl_id(declared) == normalize_dl_id(extracted)
    return False


def extract_document_numbers(document_verdict: dict[str, Any]) -> list[str]:
    """Collect all document numbers found across per-document evaluations."""
    numbers: list[str] = []
    for doc in document_verdict.get("per_document", []):
        is_dl = doc.get("doc_type") == "driving_licence"
        is_passbook = doc.get("doc_type") == "bank_passbook"
        candidates: list[str] = []
        if is_dl:
            dl_label = doc.get("dl_number_from_label")
            if dl_label:
                candidates.append(str(dl_label))
        if is_passbook:
            ac_label = doc.get("account_number_from_label")
            if ac_label:
                candidates.append(str(ac_label))
        for candidate in (
            doc.get("doc_number"),
            (doc.get("groq_extracted_fields") or {}).get("document_number"),
            (doc.get("qr_scan_result") or {}).get("qr_document_number"),
        ):
            if candidate:
                candidates.append(str(candidate))
        for raw in candidates:
            if is_dl and not is_plausible_dl_number(raw):
                continue
            if is_passbook:
                from app.services.account_cross_check import is_plausible_account_number
                if not is_plausible_account_number(raw):
                    continue
            cleaned = normalize_id(raw)
            if cleaned and cleaned not in numbers:
                numbers.append(cleaned)
    return numbers


def check_id_mismatch(
    declared_id: str,
    document_verdict: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Compare customer-declared id_number with numbers extracted from documents.
    For driving licences, matches against the DL No printed on the document.
    Returns mismatch dict or None if no mismatch / cannot compare.
    """
    declared = normalize_id(declared_id)
    if not declared:
        return None

    if not document_verdict:
        return None

    from app.services.account_cross_check import find_declared_account_in_text

    for doc in document_verdict.get("per_document", []):
        text = doc.get("text_content", "") or ""
        if find_declared_dl_in_text(declared_id, text):
            return None
        if doc.get("doc_type") == "bank_passbook" and find_declared_account_in_text(declared_id, text):
            return None

    extracted_list = extract_document_numbers(document_verdict)
    if not extracted_list:
        return None

    if any(ids_equivalent(declared_id, ext) for ext in extracted_list):
        return None

    extracted = extracted_list[0]
    declared_display = declared_id.strip()
    extracted_display = extracted
    for doc in document_verdict.get("per_document", []):
        if doc.get("dl_number_from_label") and is_plausible_dl_number(doc["dl_number_from_label"]):
            extracted_display = doc["dl_number_from_label"]
            break
        if doc.get("account_number_from_label"):
            extracted_display = doc["account_number_from_label"]
            break
        raw = (doc.get("groq_extracted_fields") or {}).get("document_number") or doc.get("doc_number")
        if raw and (doc.get("doc_type") != "driving_licence" or is_plausible_dl_number(str(raw))):
            extracted_display = str(raw)
            break

    is_dl = any(doc.get("doc_type") == "driving_licence" for doc in document_verdict.get("per_document", []))
    is_passbook = any(doc.get("doc_type") == "bank_passbook" for doc in document_verdict.get("per_document", []))
    if is_passbook:
        doc_label = "Account No"
    elif is_dl:
        doc_label = "DL No"
    else:
        doc_label = "document ID"

    return {
        "declared": declared_display,
        "extracted": extracted_display,
        "extracted_all": extracted_list,
        "reason": (
            f"ID number entered ({declared_display}) does not match the {doc_label} "
            f"on the uploaded document ({extracted_display})."
        ),
        "short_reason": (
            f"Entered ID does not match {doc_label} on the document."
            if is_dl
            else "Entered ID number does not match the number on the uploaded document."
        ),
        "severity": "critical",
    }

