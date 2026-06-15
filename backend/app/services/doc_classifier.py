"""
Indian KYC Document Classifier Service
========================================
Uses two trained XGBoost models to:
  1. Identify the type of an Indian proof document
     (Aadhaar / PAN / Passport / Voter ID / DL / Bank Passbook)
  2. Determine whether the document is VALID for KYC purposes

Feature extraction is done from document text content,
filename, and metadata produced by the document parser.

Validation criteria follow RBI KYC Master Directions 2016
(as amended) and UIDAI / NSDL / MEA / ECI specifications.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"

_type_model = None
_validity_model = None
_metadata: dict | None = None

# ── Regex patterns for Indian document numbers ────────────────────────────────
PATTERNS = {
    "aadhaar": re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b"),   # 12-digit, starts 2-9
    "pan":     re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),        # AAAAA9999A
    "passport":re.compile(r"\b[A-Z][0-9]{7}\b"),                 # A1234567
    "voter":   re.compile(r"\b[A-Z]{3}[0-9]{7}\b"),             # ABC1234567
    "dl":      re.compile(r"\b[A-Z]{2}[-\s]?\d{2}[-\s]\d{4,7}\b"),  # MH-12-1234567
    "account": re.compile(r"\b\d{9,18}\b"),                      # 9-18 digit bank account
}

# Keywords strongly associated with each doc type
KEYWORDS = {
    "aadhaar_card":    ["aadhaar", "uid", "uidai", "unique identification", "enrolment", "आधार"],
    "pan_card":        ["permanent account number", "pan", "income tax", "income-tax dept", "आयकर"],
    "passport":        ["passport", "republic of india", "nationality", "mrz", "ministry of external", "date of issue", "place of birth"],
    "voter_id":        ["election commission", "voter", "epic", "electoral", "elector", "विधानसभा", "constituency"],
    "driving_licence": ["driving licence", "driving license", "transport", "rto", "vehicle class", "dl no", "licence no"],
    "bank_passbook":   ["bank", "passbook", "account no", "ifsc", "branch", "savings account", "current account", "account holder"],
}

# Fields that each document type is expected to contain (for completeness check)
EXPECTED_FIELDS = {
    "aadhaar_card":    {"dob", "address", "gender", "photo"},
    "pan_card":        {"dob", "father", "photo"},
    "passport":        {"dob", "address", "gender", "photo", "expiry"},
    "voter_id":        {"dob", "address", "gender", "photo"},
    "driving_licence": {"dob", "address", "gender", "photo", "expiry"},
    "bank_passbook":   {"address", "ifsc"},
}

DOC_TYPES = [
    "aadhaar_card",
    "pan_card",
    "passport",
    "voter_id",
    "driving_licence",
    "bank_passbook",
]


def _load_models() -> bool:
    global _type_model, _validity_model, _metadata

    if _type_model is not None:
        return True

    type_path = MODEL_DIR / "doc_type_classifier.pkl"
    validity_path = MODEL_DIR / "doc_validity_classifier.pkl"
    meta_path = MODEL_DIR / "doc_classifier_metadata.json"

    if not type_path.exists() or not validity_path.exists():
        log.warning("Document classifier models not found — run scripts/train_document_classifier.py")
        return False

    try:
        with open(type_path, "rb") as f:
            _type_model = pickle.load(f)
        with open(validity_path, "rb") as f:
            _validity_model = pickle.load(f)
        with open(meta_path) as f:
            _metadata = json.load(f)
        log.info(
            "Document classifiers loaded (type acc=%.2f, validity acc=%.2f)",
            _metadata["type_model_metrics"]["accuracy"],
            _metadata["validity_model_metrics"]["accuracy"],
        )
        return True
    except Exception as exc:
        log.warning("Failed to load document classifiers: %s", exc)
        return False


# ── Feature extraction from document text ────────────────────────────────────

def _normalize_text(text: str) -> str:
    return (text or "").lower().strip()


def _detect_keywords(text_lower: str) -> dict[str, int]:
    """Count keyword hits per document type."""
    hits = {}
    for doc_type, kws in KEYWORDS.items():
        count = sum(1 for kw in kws if kw in text_lower)
        hits[doc_type] = count
    return hits


def _check_number_format(text: str) -> dict[str, bool]:
    """Check which document number patterns appear in text."""
    return {
        "aadhaar": bool(PATTERNS["aadhaar"].search(text)),
        "pan":     bool(PATTERNS["pan"].search(text)),
        "passport":bool(PATTERNS["passport"].search(text)),
        "voter":   bool(PATTERNS["voter"].search(text)),
        "dl":      bool(PATTERNS["dl"].search(text)),
        "account": bool(PATTERNS["account"].search(text)),
    }


def _extract_number_from_text(text: str, doc_type: str) -> str:
    """Try to extract the document number from text."""
    pattern_map = {
        "aadhaar_card":    PATTERNS["aadhaar"],
        "pan_card":        PATTERNS["pan"],
        "passport":        PATTERNS["passport"],
        "voter_id":        PATTERNS["voter"],
        "driving_licence": PATTERNS["dl"],
        "bank_passbook":   PATTERNS["account"],
    }
    pat = pattern_map.get(doc_type)
    if pat:
        m = pat.search(text)
        if m:
            return m.group(0).replace(" ", "")
    return ""


def _check_name_in_text(text_lower: str, customer_name: str) -> bool:
    """Fuzzy check if customer name appears in document text."""
    if not customer_name or not text_lower:
        return False
    name_parts = customer_name.lower().split()
    matches = sum(1 for part in name_parts if len(part) > 2 and part in text_lower)
    return matches >= min(2, len(name_parts))


def _check_expiry(text_lower: str) -> tuple[bool, bool]:
    """Return (has_expiry, is_valid_expiry). Uses date patterns in text."""
    date_patterns = [
        re.compile(r"\bvalid till[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE),
        re.compile(r"\bexpiry[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE),
        re.compile(r"\bvalid upto[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE),
        re.compile(r"\bexpires?[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE),
        re.compile(r"\bdate of expiry[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE),
    ]
    for pat in date_patterns:
        m = pat.search(text_lower)
        if m:
            try:
                parts = m.group(1).split("/")
                exp_year = int(parts[2])
                return True, exp_year >= 2025
            except Exception:
                return True, False
    return False, True


def _parse_expiry_from_groq(expiry_str: str | None) -> tuple[bool, bool]:
    """Parse expiry date string returned by Groq."""
    if not expiry_str:
        return False, True  # no expiry = valid (Aadhaar/PAN)
    try:
        parts = str(expiry_str).strip().split("/")
        if len(parts) == 3:
            year = int(parts[2])
            return True, year >= 2025
    except Exception:
        pass
    return True, False


def _check_ifsc(text: str) -> bool:
    ifsc_pat = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
    return bool(ifsc_pat.search(text))


def _check_dob(text: str) -> bool:
    dob_patterns = [
        re.compile(r"\bdob\b", re.IGNORECASE),
        re.compile(r"date of birth", re.IGNORECASE),
        re.compile(r"\bborn\b", re.IGNORECASE),
        re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
        re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    ]
    return any(p.search(text) for p in dob_patterns)


def _check_address(text_lower: str) -> tuple[bool, bool]:
    address_markers = [
        "address", "house no", "flat no", "village", "district",
        "state", "pin", "pincode", "post", "tehsil", "taluk",
        "road", "nagar", "colony", "street", "ward",
    ]
    hits = sum(1 for m in address_markers if m in text_lower)
    has_address = hits >= 2
    complete = hits >= 4
    return has_address, complete


def _check_gender(text_lower: str) -> bool:
    gender_terms = ["male", "female", "m / पुरुष", "f / महिला", "gender", "sex :", "sex:"]
    return any(t in text_lower for t in gender_terms)


def _check_photo(text_lower: str, is_image: bool, extraction_method: str) -> bool:
    if is_image:
        return True
    photo_terms = ["photograph", "photo", "image"]
    return any(t in text_lower for t in photo_terms) or extraction_method == "image"


def _check_signature(text_lower: str) -> bool:
    sig_terms = ["signature", "sign", "authorized signatory", "attested by"]
    return any(t in text_lower for t in sig_terms)


def _check_qr_barcode(text_lower: str) -> bool:
    terms = ["qr", "barcode", "mrz", "machine readable", "ifsc"]
    return any(t in text_lower for t in terms)


def _check_issuer(text_lower: str, doc_type: str) -> bool:
    issuer_map = {
        "aadhaar_card":    ["uidai", "unique identification authority"],
        "pan_card":        ["income tax", "nsdl"],
        "passport":        ["ministry of external affairs", "passport authority", "republic of india"],
        "voter_id":        ["election commission", "electoral"],
        "driving_licence": ["transport authority", "rto", "motor vehicle"],
        "bank_passbook":   ["bank", "ifsc", "rbi approved"],
    }
    terms = issuer_map.get(doc_type, [])
    return any(t in text_lower for t in terms)


# ── Feature extraction: text-based (fallback) ────────────────────────────────

def extract_doc_features(
    text_content: str,
    filename: str,
    is_image: bool,
    extraction_method: str,
    customer_name: str = "",
    declared_doc_type: str | None = None,
    groq_fields: dict | None = None,          # ← NEW: Groq-extracted fields
) -> tuple[dict, str, str]:
    """
    Extract structured features from document text for ML classification.

    When groq_fields is provided (from Groq LLM extraction), those field
    values take priority over the regex/keyword heuristics. This gives the
    XGBoost model richer, more reliable inputs.

    Returns (features_dict, inferred_type, doc_number).
    """
    text_lower = _normalize_text(text_content)
    original_text = text_content or ""
    gf = groq_fields or {}  # Groq-extracted fields dict

    # ── Step 1: Infer document type ──────────────────────────────────────────
    # Groq-detected type takes priority over regex heuristics
    groq_doc_type = gf.get("detected_doc_type", "")
    if groq_doc_type and groq_doc_type in DOC_TYPES:
        inferred_type = groq_doc_type
    elif declared_doc_type:
        inferred_type = declared_doc_type
    else:
        keyword_hits = _detect_keywords(text_lower)
        num_checks   = _check_number_format(original_text)
        if num_checks["aadhaar"] or keyword_hits["aadhaar_card"] >= 1:
            inferred_type = "aadhaar_card"
        elif num_checks["pan"] or keyword_hits["pan_card"] >= 1:
            inferred_type = "pan_card"
        elif num_checks["passport"] or keyword_hits["passport"] >= 1:
            inferred_type = "passport"
        elif num_checks["voter"] or keyword_hits["voter_id"] >= 1:
            inferred_type = "voter_id"
        elif num_checks["dl"] or keyword_hits["driving_licence"] >= 1:
            inferred_type = "driving_licence"
        elif num_checks["account"] or keyword_hits["bank_passbook"] >= 1:
            inferred_type = "bank_passbook"
        else:
            best = max(keyword_hits, key=lambda k: keyword_hits[k]) if any(keyword_hits.values()) else None
            inferred_type = best or "unknown"

    num_checks = _check_number_format(original_text)

    # ── Step 2: Extract fields — Groq values override regex ──────────────────
    ef = gf.get("extracted_fields", {})   # Groq extracted_fields sub-dict
    pm = gf.get("profile_match", {})      # Groq profile_match sub-dict
    di = gf.get("document_integrity", {}) # Groq document_integrity sub-dict

    # Document number
    groq_doc_num = ef.get("document_number") or ""
    if groq_doc_num and groq_doc_num not in ("null", "None", None):
        doc_number    = str(groq_doc_num).replace(" ", "").strip()
        has_doc_number = True
    else:
        doc_number = _extract_number_from_text(original_text, inferred_type)
        has_doc_number = bool(doc_number) or any(num_checks.values())
    doc_number_len = len(doc_number) if doc_number else 0

    # Validate number format for the detected type
    doc_number_format_ok = False
    if inferred_type == "aadhaar_card":
        doc_number_format_ok = bool(PATTERNS["aadhaar"].match(doc_number)) if doc_number else num_checks["aadhaar"]
    elif inferred_type == "pan_card":
        doc_number_format_ok = bool(PATTERNS["pan"].fullmatch(doc_number)) if doc_number else num_checks["pan"]
    elif inferred_type == "passport":
        doc_number_format_ok = bool(PATTERNS["passport"].fullmatch(doc_number)) if doc_number else num_checks["passport"]
    elif inferred_type == "voter_id":
        doc_number_format_ok = bool(PATTERNS["voter"].fullmatch(doc_number)) if doc_number else num_checks["voter"]
    elif inferred_type == "driving_licence":
        doc_number_format_ok = bool(PATTERNS["dl"].search(doc_number)) if doc_number else num_checks["dl"]
    elif inferred_type == "bank_passbook":
        doc_number_format_ok = bool(PATTERNS["account"].fullmatch(doc_number)) if doc_number else num_checks["account"]

    # Name
    groq_name = ef.get("full_name")
    if groq_name and groq_name not in ("null", "None", None):
        has_name = True
        # Use Groq name-match score if available
        groq_name_match = pm.get("name_matches")
        name_matches_profile = groq_name_match if isinstance(groq_name_match, bool) else (
            _check_name_in_text(str(groq_name).lower(), customer_name)
        )
    else:
        has_name = "name" in text_lower or _check_name_in_text(text_lower, customer_name)
        name_matches_profile = _check_name_in_text(text_lower, customer_name)

    # DOB
    groq_dob = ef.get("date_of_birth")
    has_dob = (groq_dob is not None and str(groq_dob) not in ("null", "None", "")) or _check_dob(original_text)

    # Address
    groq_address = ef.get("address")
    if groq_address and str(groq_address) not in ("null", "None", ""):
        has_address = True
        address_complete = len(str(groq_address)) > 20
    else:
        has_address, address_complete = _check_address(text_lower)

    # Gender
    groq_gender = ef.get("gender")
    has_gender = (groq_gender is not None and str(groq_gender) not in ("null", "None", "")) or _check_gender(text_lower)

    # Photo
    groq_photo = ef.get("photo_present")
    if isinstance(groq_photo, bool):
        has_photo = groq_photo
    else:
        has_photo = _check_photo(text_lower, is_image, extraction_method)

    # Signature
    groq_sig = ef.get("signature_present")
    has_signature = bool(groq_sig) if isinstance(groq_sig, bool) else _check_signature(text_lower)

    # QR / Barcode / MRZ / IFSC
    groq_qr  = ef.get("qr_or_barcode_present")
    groq_mrz = ef.get("mrz_present")
    groq_ifsc = ef.get("ifsc_code")
    has_qr_barcode = (
        (isinstance(groq_qr,  bool) and groq_qr)
        or (isinstance(groq_mrz, bool) and groq_mrz)
        or (groq_ifsc and str(groq_ifsc) not in ("null", "None", ""))
        or _check_qr_barcode(text_lower)
        or _check_ifsc(original_text)
    )

    # Expiry
    groq_expiry = ef.get("expiry_date")
    if groq_expiry and str(groq_expiry) not in ("null", "None", ""):
        has_expiry, expiry_valid = _parse_expiry_from_groq(str(groq_expiry))
    else:
        has_expiry, expiry_valid = _check_expiry(text_lower)

    # Issuer
    groq_issuer = ef.get("issuing_authority")
    if groq_issuer and str(groq_issuer) not in ("null", "None", ""):
        has_issuer = True
    else:
        has_issuer = _check_issuer(text_lower, inferred_type)

    # Enrolment number (Aadhaar-specific)
    has_enrolment_no = "enrolment" in text_lower or "enrollment" in text_lower

    # Secondary language
    groq_lang = ef.get("language_secondary")
    if isinstance(groq_lang, bool):
        language_secondary = groq_lang
    else:
        language_secondary = any(
            ch in original_text
            for ch in "आभईउओकखगघचछजझटठडढणतथदधनपफबभमयरलवशषसहािीुूेैोौ"
        )

    # Integrity score from Groq (0-1) → use as feature signal
    groq_integrity = di.get("integrity_score", None)

    # POI / POA flags from metadata
    from app.services.doc_classifier import _metadata as meta
    purpose = {}
    if meta:
        purpose = meta.get("doc_kyc_purpose", {}).get(inferred_type or "", {})
    is_poi = purpose.get("poi", inferred_type not in ("bank_passbook",))
    is_poa = purpose.get("poa", inferred_type != "pan_card")

    # ── Step 3: Derived features ──────────────────────────────────────────────
    expected_lengths = {
        "aadhaar_card": 12, "pan_card": 10, "passport": 8,
        "voter_id": 10, "driving_licence": 15, "bank_passbook": 13,
    }
    expected_len = expected_lengths.get(inferred_type or "", 10)
    number_length_diff = abs(doc_number_len - expected_len) if doc_number_len else expected_len

    completeness_vals = [
        int(has_doc_number), int(has_name), int(has_dob),
        int(has_address), int(has_gender), int(has_photo), int(has_issuer),
    ]
    completeness_score = sum(completeness_vals) / len(completeness_vals)

    # Trust signal: Groq integrity score takes precedence if available
    if isinstance(groq_integrity, (int, float)):
        trust_signal_score = float(groq_integrity)
    else:
        trust_signal_score = (
            int(has_photo)            * 0.20
            + int(has_signature)      * 0.10
            + int(has_qr_barcode)     * 0.15
            + int(has_issuer)         * 0.20
            + int(doc_number_format_ok) * 0.20
            + int(name_matches_profile) * 0.15
        )

    expiry_concern = int(has_expiry and not expiry_valid)

    features = {
        "has_doc_number":           int(has_doc_number),
        "doc_number_length":        doc_number_len,
        "doc_number_format_ok":     int(doc_number_format_ok),
        "has_name":                 int(has_name),
        "has_dob":                  int(has_dob),
        "has_address":              int(has_address),
        "has_gender":               int(has_gender),
        "has_photo":                int(has_photo),
        "has_expiry":               int(has_expiry),
        "expiry_valid":             int(expiry_valid),
        "has_issuer":               int(has_issuer),
        "has_signature":            int(has_signature),
        "has_qr_or_barcode":        int(has_qr_barcode),
        "has_enrolment_no":         int(has_enrolment_no),
        "name_matches_profile":     int(name_matches_profile),
        "address_complete":         int(address_complete),
        "language_secondary_present": int(language_secondary),
        "is_poi":                   int(is_poi),
        "is_poa":                   int(is_poa),
        "number_length_diff":       number_length_diff,
        "completeness_score":       completeness_score,
        "trust_signal_score":       trust_signal_score,
        "expiry_concern":           expiry_concern,
    }
    return features, inferred_type, doc_number


# ── Public inference function ────────────────────────────────────────────────

def classify_document(
    text_content: str,
    filename: str,
    is_image: bool,
    extraction_method: str,
    customer_name: str = "",
    declared_doc_type: str | None = None,
    groq_fields: dict | None = None,    # ← Groq-extracted fields, if available
) -> dict[str, Any]:
    """
    Classify a document and assess its validity for Indian KYC.

    When groq_fields is supplied (from extract_fields_from_document),
    those LLM-extracted values enrich the XGBoost feature vector,
    giving the model much more reliable inputs than regex alone.
    """
    if not _load_models():
        return {
            "ml_used": False,
            "doc_type": declared_doc_type or "unknown",
            "is_valid": None,
            "validity_issues": ["Document classifier model not available"],
        }

    features, inferred_type, doc_number = extract_doc_features(
        text_content=text_content,
        filename=filename,
        is_image=is_image,
        extraction_method=extraction_method,
        customer_name=customer_name,
        declared_doc_type=declared_doc_type,
        groq_fields=groq_fields,
    )

    feat_order_type = _metadata["features_type"]
    feat_order_validity = _metadata["features_validity"]

    X_type = np.array([[features[f] for f in feat_order_type]], dtype=float)

    # ── Predict document type ─────────────────────────────────────────────────
    type_proba = _type_model.predict_proba(X_type)[0]
    pred_type_idx = int(np.argmax(type_proba))
    pred_type = DOC_TYPES[pred_type_idx]
    type_confidence = float(type_proba[pred_type_idx])

    all_type_probs = {DOC_TYPES[i]: round(float(p), 4) for i, p in enumerate(type_proba)}

    # Use ML type if not declared
    final_type = declared_doc_type or pred_type

    # ── Predict validity ──────────────────────────────────────────────────────
    doc_type_label = DOC_TYPES.index(final_type) if final_type in DOC_TYPES else pred_type_idx
    features["doc_type_label"] = doc_type_label

    X_validity = np.array([[features[f] for f in feat_order_validity]], dtype=float)
    validity_proba = _validity_model.predict_proba(X_validity)[0]
    pred_valid = bool(np.argmax(validity_proba))
    validity_confidence = float(validity_proba[int(pred_valid)])

    # ── Build validity issues list ────────────────────────────────────────────
    # Start with Groq integrity issues if available
    issues = []
    if groq_fields:
        di = groq_fields.get("document_integrity", {})
        groq_integrity_issues = di.get("integrity_issues", [])
        for gi in (groq_integrity_issues or []):
            gi_str = str(gi).strip()
            if gi_str:
                # Skip generic low-confidence notes that are not real integrity failures
                if not any(kw in gi_str.lower() for kw in (
                    "no visible signs of tampering",
                    "image quality",
                    "readability",
                )):
                    issues.append(f"[Groq] {gi_str}")

        pm = groq_fields.get("profile_match", {})
        for mm in (pm.get("mismatch_details") or []):
            mm_str = str(mm).strip()
            if not mm_str:
                continue
            mm_lower = mm_str.lower()
            # Skip DOB mismatches that are just year vs full-date formatting differences
            # e.g. "declared as 2002-01-01, document only shows year 2002"
            if any(kw in mm_lower for kw in (
                "only shows year",
                "only year",
                "year only",
                "year of birth",
                "dob format",
                "date format",
                "document only shows year",
            )):
                continue
            # Also skip if mismatch is just a DOB year that matches the declared year
            if "dob" in mm_lower or "date of birth" in mm_lower or "birth" in mm_lower:
                import re as _re
                declared_year = _re.search(r"\b(19|20)\d{2}\b", str(customer_name))
                # If the mismatch is about DOB and contains matching years, skip it
                years_in_msg = _re.findall(r"\b(19|20)\d{2}\b", mm_str)
                if len(set(years_in_msg)) == 1:
                    # Only one year mentioned — same year, just format difference
                    continue
                if len(years_in_msg) >= 2 and years_in_msg[0] == years_in_msg[1]:
                    continue
            issues.append(f"[Profile mismatch] {mm_str}")

    rules = _metadata.get("validity_rules", {}).get(final_type, {})

    if not features["has_doc_number"]:
        issues.append("Document number not found")
    elif not features["doc_number_format_ok"]:
        issues.append(f"Document number format invalid (expected: {rules.get('description', '')})")

    if not features["has_name"]:
        issues.append("Name not found in document")

    if final_type not in ("bank_passbook",) and not features["has_dob"]:
        issues.append("Date of birth not found")

    if final_type in ("aadhaar_card", "passport", "voter_id", "driving_licence") and not features["has_address"]:
        issues.append("Address not found")

    if features["expiry_concern"]:
        issues.append("Document has expired — not acceptable for KYC")

    if final_type in ("passport",) and not features["has_qr_or_barcode"]:
        issues.append("MRZ (Machine Readable Zone) not detected")

    if final_type in ("bank_passbook",) and not features["has_qr_or_barcode"]:
        issues.append("IFSC code not found in passbook")

    if not features["has_photo"] and final_type not in ("bank_passbook",):
        issues.append("Photograph not detected")

    if features["completeness_score"] < 0.5:
        issues.append(f"Document completeness low ({features['completeness_score']:.0%})")

    kyc_purpose = _metadata.get("doc_kyc_purpose", {}).get(final_type, {"poi": False, "poa": False})

    # Groq-extracted fields summary to include in result
    groq_extracted_summary = {}
    if groq_fields:
        ef = groq_fields.get("extracted_fields", {})
        groq_extracted_summary = {
            k: v for k, v in ef.items()
            if v is not None and str(v) not in ("null", "None", "")
        }

    return {
        "ml_used": True,
        "doc_type": final_type,
        "doc_type_display": final_type.replace("_", " ").title(),
        "doc_type_confidence": round(type_confidence, 4),
        "all_type_probabilities": all_type_probs,
        "is_valid": pred_valid,
        "validity_confidence": round(validity_confidence, 4),
        "validity_issues": issues,
        "doc_number": doc_number,
        "kyc_purpose": kyc_purpose,
        "completeness_score": round(features["completeness_score"], 3),
        "trust_signal_score": round(features["trust_signal_score"], 3),
        "features_extracted": features,
        "groq_extracted_fields": groq_extracted_summary,  # ← new
    }
