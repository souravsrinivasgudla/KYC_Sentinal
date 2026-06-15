"""Cross-check declared ID number against numbers extracted from uploaded documents."""

from __future__ import annotations

import re
from typing import Any


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_id(value: str) -> str:
    """Normalize ID for comparison (Aadhaar digits-only, PAN alphanumeric)."""
    v = (value or "").strip().upper()
    digits = _digits_only(v)
    # 12-digit Aadhaar
    if len(digits) == 12:
        return digits
    return re.sub(r"[\s\-]", "", v)


def extract_document_numbers(document_verdict: dict[str, Any]) -> list[str]:
    """Collect all document numbers found across per-document evaluations."""
    numbers: list[str] = []
    for doc in document_verdict.get("per_document", []):
        for candidate in (
            doc.get("doc_number"),
            (doc.get("groq_extracted_fields") or {}).get("document_number"),
            (doc.get("qr_scan_result") or {}).get("qr_document_number"),
        ):
            if candidate:
                cleaned = normalize_id(str(candidate))
                if cleaned and cleaned not in numbers:
                    numbers.append(cleaned)
    return numbers


def check_id_mismatch(
    declared_id: str,
    document_verdict: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Compare customer-declared id_number with numbers extracted from documents.
    Returns mismatch dict or None if no mismatch / cannot compare.
    """
    declared = normalize_id(declared_id)
    if not declared:
        return None

    if not document_verdict:
        return None

    extracted_list = extract_document_numbers(document_verdict)
    if not extracted_list:
        return None

    # Match if any extracted number equals declared
    if any(declared == ext for ext in extracted_list):
        return None

    # Use the first extracted as the canonical document number
    extracted = extracted_list[0]
    return {
        "declared": declared,
        "extracted": extracted,
        "extracted_all": extracted_list,
        "reason": (
            f"ID number entered ({declared}) does not match the uploaded document ({extracted})."
        ),
        "short_reason": "Entered ID number does not match the number on the uploaded document.",
        "severity": "critical",
    }
