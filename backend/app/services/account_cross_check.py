"""Extract and compare bank account numbers from passbook documents."""

from __future__ import annotations

import re
from typing import Any

ACCOUNT_DIGITS = re.compile(r"\d{9,18}")

ACCOUNT_LABEL_PATTERNS = [
    re.compile(r"acc(?:ount)?\s*(?:no|number|#)?\.?\s*[:\-]?\s*(\d[\d\s\-/]{7,22})", re.IGNORECASE),
    re.compile(r"a\s*/\s*c\s*(?:no|number|#)?\.?\s*[:\-]?\s*(\d[\d\s\-/]{7,22})", re.IGNORECASE),
    re.compile(r"acct\s*(?:no|number|#)?\.?\s*[:\-]?\s*(\d[\d\s\-/]{7,22})", re.IGNORECASE),
    re.compile(r"account\s*(?:no|number|#)?\.?\s*[:\-]?\s*(\d[\d\s\-/]{7,22})", re.IGNORECASE),
    re.compile(r"savings\s*account\s*(?:no|number)?\.?\s*[:\-]?\s*(\d[\d\s\-/]{7,22})", re.IGNORECASE),
    re.compile(r"current\s*account\s*(?:no|number)?\.?\s*[:\-]?\s*(\d[\d\s\-/]{7,22})", re.IGNORECASE),
]

_LABEL_VALUE_STOP = re.compile(
    r"\b(ifsc|branch|micr|cheque|balance|date|txn|transaction|deposit|withdraw)\b",
    re.IGNORECASE,
)


def normalize_account_number(value: str) -> str:
    """Digits-only account number for comparison."""
    return re.sub(r"\D", "", value or "")


def is_account_format(value: str) -> bool:
    digits = normalize_account_number(value)
    return 9 <= len(digits) <= 18


def is_plausible_account_number(value: str) -> bool:
    if not value or not str(value).strip():
        return False
    digits = normalize_account_number(value)
    if not (9 <= len(digits) <= 18):
        return False
    # Reject obvious dates (DDMMYYYY = 8 digits often wrong context — already filtered by min 9)
    if len(set(digits)) == 1:
        return False
    return True


def _trim_label_capture(raw: str) -> str:
    trimmed = _LABEL_VALUE_STOP.split(raw, maxsplit=1)[0].strip()
    return trimmed or raw.strip()


def _extract_digits_from_raw(raw: str) -> str:
    raw = _trim_label_capture(raw)
    dm = ACCOUNT_DIGITS.search(re.sub(r"[\s\-/]", "", raw))
    if dm:
        return dm.group(0)
    m = ACCOUNT_DIGITS.search(raw)
    return m.group(0) if m else ""


def extract_account_number_from_text(text: str, declared_id: str = "") -> str:
    """
    Extract account number from passbook text, preferring ACC No / Account No labels.
    """
    if not text and not declared_id:
        return ""

    if declared_id and is_account_format(declared_id):
        declared_digits = normalize_account_number(declared_id)
        text_norm = normalize_account_number(text)
        if declared_digits and declared_digits in text_norm:
            return declared_digits

    for pat in ACCOUNT_LABEL_PATTERNS:
        m = pat.search(text or "")
        if m:
            digits = _extract_digits_from_raw(m.group(1))
            if is_plausible_account_number(digits):
                return digits

    if declared_id and is_account_format(declared_id):
        for m in ACCOUNT_DIGITS.finditer(text or ""):
            if accounts_equivalent(declared_id, m.group(0)):
                return normalize_account_number(m.group(0))

    return ""


def accounts_equivalent(declared: str, extracted: str) -> bool:
    if not declared or not extracted:
        return False
    return normalize_account_number(declared) == normalize_account_number(extracted)


def find_declared_account_in_text(declared: str, text: str) -> str:
    if not declared or not text:
        return ""
    if not is_account_format(declared):
        return ""
    target = normalize_account_number(declared)
    if target in normalize_account_number(text):
        return target
    for m in ACCOUNT_DIGITS.finditer(text):
        if accounts_equivalent(declared, m.group(0)):
            return normalize_account_number(m.group(0))
    return ""


def account_format_ok(doc_number: str) -> bool:
    return is_plausible_account_number(doc_number)
