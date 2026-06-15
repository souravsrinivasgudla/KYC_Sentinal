"""
Indian Document Verification Agent
====================================
Four-stage pipeline per uploaded document:

  Stage 1 — Groq LLM / Vision Field Extraction
  ──────────────────────────────────────────────
  • Images / scanned PDFs → Groq Vision (Llama 4 Scout)
    reads the actual pixels and extracts all visible fields.
  • Text PDFs / .txt → Groq text model reads extracted text.

  Stage 1b — HuggingFace QR Fallback (conditional)
  ──────────────────────────────────────────────────
  Triggered ONLY when Stage 1 finds NO document number
  but the image contains a QR code / barcode.

  Step A: OpenCV QRCodeDetector decodes the binary QR
          payload directly from the image (no network).
          Aadhaar QR yields full XML with uid, name, DOB,
          address, gender, pincode.

  Step B: Rule-based cross-match (hf_document_extractor)
          compares QR-decoded fields vs Groq-extracted
          visual fields: name token-overlap, year-of-birth,
          gender, document number.
          • Match  → QR number accepted as document number
          • Mismatch → tampering flag, integrity score drops

  Step C (optional fallback): If OpenCV QR decode fails,
          TrOCR (microsoft/trocr-base-printed) from
          HuggingFace runs line-level OCR on the image and
          the resulting text is sent to Groq for structured
          parsing and cross-match.

  Stage 2 — XGBoost ML Verification
  ────────────────────────────────────
  The fully enriched feature vector feeds both XGBoost
  models:
    • doc_type_classifier    → which Indian KYC doc type?
    • doc_validity_classifier → is this document valid?

  Final verdict per document:
    VERIFIED     — all checks pass
    NEEDS_REVIEW — borderline; human review required
    REJECTED     — hard failure; pipeline short-circuits
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.doc_classifier import classify_document, DOC_TYPES
from app.services.evidence_store import get_evidence
from app.services.groq_client import (
    cross_match_qr_vs_text,
    extract_fields_from_document,
    extract_fields_from_image,
    scan_qr_from_document,
)

log = logging.getLogger(__name__)

# ── Verdict thresholds ────────────────────────────────────────────────────────
VERIFIED_VALIDITY_CONF = 0.65
VERIFIED_TYPE_CONF     = 0.75
NEEDS_REVIEW_TYPE      = 0.55

DOC_DISPLAY = {
    "aadhaar_card":    "Aadhaar Card",
    "pan_card":        "PAN Card",
    "passport":        "Passport",
    "voter_id":        "Voter ID (EPIC)",
    "driving_licence": "Driving Licence",
    "bank_passbook":   "Bank Passbook",
    "unknown":         "Unrecognised Document",
}

REQUIRE_POI = True
REQUIRE_POA = False


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sanitize_groq_dl_extraction(groq_doc: dict, declared_id: str) -> None:
    """Remove date false-positives from Groq DL fields; align id_number_matches."""
    from app.services.id_cross_check import (
        ids_equivalent,
        is_dl_format,
        is_plausible_dl_number,
    )

    if groq_doc.get("detected_doc_type") != "driving_licence":
        return

    ef = dict(groq_doc.get("extracted_fields") or {})
    doc_num = str(ef.get("document_number") or "").strip()
    pm = dict(groq_doc.get("profile_match") or {})

    if doc_num and not is_plausible_dl_number(doc_num):
        ef["document_number"] = None
        doc_num = ""

    if declared_id and doc_num:
        pm["id_number_matches"] = ids_equivalent(declared_id, doc_num)
    elif (
        declared_id
        and is_dl_format(declared_id)
        and pm.get("id_number_matches") is True
    ):
        ef["document_number"] = declared_id.strip().upper()

    groq_doc["extracted_fields"] = ef
    groq_doc["profile_match"] = pm


def _run_groq_extraction(
    uploaded: list[dict],
    customer_profile: dict,
) -> dict[str, dict]:
    """
    Groq LLM first-pass field extraction for all documents.

    Routing logic:
      - Image files (jpg/png/webp) or scanned PDFs (needs_vision=True)
        → Groq Vision (Llama 4 Scout) reads the actual image pixels
      - Text-based PDFs and .txt files
        → Groq text model reads the extracted text

    Returns {filename → groq_doc_result}.
    """
    if not uploaded:
        return {}

    result_map: dict[str, dict] = {}
    declared_id = str(customer_profile.get("id_number") or "").strip()

    # Vision path: images, scanned PDFs, and text PDFs with extractable page images
    vision_docs = [
        d for d in uploaded
        if d.get("image_base64") or d.get("is_image") or d.get("needs_vision")
    ]
    vision_fnames = {d.get("original_filename") for d in vision_docs}
    text_docs = [
        d for d in uploaded
        if d.get("original_filename") not in vision_fnames
        and d.get("extraction_method") in ("pypdf", "text")
        and len((d.get("text_content") or "").strip()) >= 30
    ]

    # ── Vision path: one call per image document ──────────────────────────────
    for doc in vision_docs:
        fname      = doc.get("original_filename", "")
        img_b64    = doc.get("image_base64")
        media_type = doc.get("image_media_type", "image/jpeg")

        if not img_b64:
            log.warning("  Vision needed for '%s' but no image_base64 available — skipping", fname)
            continue

        log.info("  Groq Vision extracting fields from image: '%s'", fname)
        try:
            vision_result = extract_fields_from_image(
                image_base64=img_b64,
                media_type=media_type,
                filename=fname,
                customer_profile=customer_profile,
            )
            if vision_result.get("parse_error") or vision_result.get("fallback"):
                log.warning("  Vision extraction failed for '%s': %s", fname, vision_result.get("error"))
                continue
            for doc_result in vision_result.get("documents", []):
                result_fname = doc_result.get("filename", fname)
                doc_result["_extraction_method"] = "vision"
                _sanitize_groq_dl_extraction(doc_result, declared_id)
                result_map[result_fname] = doc_result
                log.info(
                    "  Vision extracted: type=%s, doc_number=%s, name=%s",
                    doc_result.get("detected_doc_type"),
                    doc_result.get("extracted_fields", {}).get("document_number"),
                    doc_result.get("extracted_fields", {}).get("full_name"),
                )
        except Exception as exc:
            log.warning("  Vision extraction error for '%s': %s", fname, exc)

    # ── Text path: batch call for all text documents ──────────────────────────
    if text_docs:
        doc_payload = [
            {
                "filename":          d.get("original_filename", ""),
                "text_content":      d.get("text_content", ""),
                "extraction_method": d.get("extraction_method", ""),
                "is_image":          False,
            }
            for d in text_docs
        ]
        try:
            groq_response = extract_fields_from_document(customer_profile, doc_payload)
            if not (groq_response.get("parse_error") or groq_response.get("fallback")):
                for doc_result in groq_response.get("documents", []):
                    fname = doc_result.get("filename", "")
                    if fname:
                        doc_result["_extraction_method"] = "text"
                        _sanitize_groq_dl_extraction(doc_result, declared_id)
                        result_map[fname] = doc_result
            else:
                log.warning("Groq text extraction returned non-parseable response")
        except Exception as exc:
            log.warning("Groq text extraction failed: %s", exc)

    return result_map


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1b — QR / Barcode fallback
# ─────────────────────────────────────────────────────────────────────────────

def _null_or_empty(val: Any) -> bool:
    """Return True if value is absent, null, or empty string."""
    return val is None or str(val).strip().lower() in ("", "null", "none")


def _get_image_bytes(doc: dict) -> bytes | None:
    """
    Return raw image bytes for a document dict.
    Tries stored_path first (most reliable), then reconstructs
    from image_base64 if available.
    """
    stored = doc.get("stored_path")
    if stored:
        p = Path(stored)
        if p.exists():
            return p.read_bytes()
    # Fallback: decode from base64
    b64 = doc.get("image_base64") or doc.get("base64_preview")
    if b64:
        import base64
        try:
            return base64.b64decode(b64)
        except Exception:
            pass
    return None


def _run_qr_fallback(
    doc: dict,
    groq_doc: dict,
    customer_profile: dict,
) -> dict[str, Any]:
    """
    HuggingFace QR fallback pipeline for a single document.

    Triggered when Stage 1 found no document_number but QR/barcode
    is reported as present in the image.

    Step A — OpenCV binary QR decode (no network, no Groq)
    ────────────────────────────────────────────────────────
    cv2.QRCodeDetector reads the real QR payload directly from
    the image bytes. Aadhaar QR contains XML with uid (12-digit
    number), name, DOB year, gender, and full address.

    Step B — Rule-based cross-match (hf_document_extractor)
    ────────────────────────────────────────────────────────
    Compares QR-decoded fields vs Groq-extracted visual fields:
      • name token-overlap ≥ 0.6  → match
      • year-of-birth must agree
      • gender M/F must agree
    No Groq call needed for this comparison.

    Step C — TrOCR fallback (if OpenCV QR fails)
    ──────────────────────────────────────────────
    If OpenCV can't decode the QR, run TrOCR line OCR on the
    image, then send the raw OCR lines to Groq for structured
    field parsing + cross-match.

    Returns enriched groq_doc with _qr_scan, _qr_cross_match,
    _qr_used, _qr_fallback_note, _hf_method metadata.
    """
    from app.services.hf_document_extractor import (
        decode_qr_from_image,
        extract_text_trocr,
        cross_match_qr_vs_visual,
    )

    fname        = doc.get("original_filename", "")
    doc_type     = groq_doc.get("detected_doc_type", "unknown")
    ef           = groq_doc.get("extracted_fields", {})
    image_bytes  = _get_image_bytes(doc)

    log.info("  Stage 1b QR fallback for '%s' (type=%s)", fname, doc_type)

    # ── Step A: OpenCV QR binary decode ──────────────────────────────────────
    qr_result: dict[str, Any] = {"qr_found": False}
    if image_bytes:
        log.info("  Step A: OpenCV QR decode...")
        qr_result = decode_qr_from_image(image_bytes)
        log.info(
            "  QR decode: found=%s type=%s number=%s method=%s",
            qr_result.get("qr_found"),
            qr_result.get("qr_type"),
            qr_result.get("document_number"),
            qr_result.get("decode_method"),
        )
    else:
        log.info("  Step A: No image bytes available for QR decode")

    qr_found  = bool(qr_result.get("qr_found"))
    qr_number = qr_result.get("document_number")

    # ── Step C: TrOCR fallback if OpenCV QR failed ────────────────────────────
    trocr_result: dict[str, Any] = {}
    if not qr_found and image_bytes:
        log.info("  Step C: OpenCV QR failed → TrOCR line OCR fallback")
        trocr_result = extract_text_trocr(image_bytes)
        if trocr_result.get("trocr_available") and trocr_result.get("text_lines"):
            log.info(
                "  TrOCR extracted %d lines — sending to Groq for parsing",
                trocr_result["line_count"],
            )
            # Feed TrOCR output to Groq text model for structured field extraction
            try:
                ocr_text = trocr_result["full_text"]
                groq_ocr_response = extract_fields_from_document(
                    customer_profile,
                    [{
                        "filename":          fname,
                        "text_content":      f"[TrOCR OCR output]\n{ocr_text}",
                        "extraction_method": "trocr",
                        "is_image":          False,
                    }],
                )
                if not groq_ocr_response.get("parse_error"):
                    for doc_result in groq_ocr_response.get("documents", []):
                        trocr_ef = doc_result.get("extracted_fields", {})
                        trocr_num = trocr_ef.get("document_number")
                        if not _null_or_empty(trocr_num):
                            qr_number = trocr_num
                            qr_found  = True
                            qr_result = {
                                "qr_found":        True,
                                "qr_type":         "trocr_ocr",
                                "document_number": trocr_num,
                                "full_name":       trocr_ef.get("full_name"),
                                "gender":          trocr_ef.get("gender"),
                                "date_of_birth":   trocr_ef.get("date_of_birth"),
                                "year_of_birth":   None,
                                "address":         trocr_ef.get("address"),
                                "raw_payload":     ocr_text[:300],
                                "all_fields":      trocr_ef,
                                "decode_method":   "trocr+groq",
                            }
                            log.info("  TrOCR+Groq found doc number: %s", trocr_num)
            except Exception as exc:
                log.warning("  TrOCR Groq parse failed: %s", exc)

    if not qr_found or _null_or_empty(qr_number):
        enriched = dict(groq_doc)
        enriched["_qr_scan"]         = qr_result
        enriched["_qr_cross_match"]  = {}
        enriched["_qr_used"]         = False
        enriched["_qr_fallback_note"] = (
            "QR detected visually but no document number could be recovered. "
            f"OpenCV: {qr_result.get('decode_method', 'n/a')} "
            + (f"| TrOCR: {trocr_result.get('line_count', 0)} lines" if trocr_result else "")
        )
        enriched["_hf_method"] = "opencv_failed"
        return enriched

    # ── Step B: Cross-match QR fields vs Groq-extracted visual fields ─────────
    log.info("  Step B: Cross-matching QR fields vs visual fields (rule-based)")
    qr_all_fields = qr_result.get("all_fields", qr_result)

    cross = cross_match_qr_vs_visual(
        visual_fields=ef,
        qr_fields=qr_all_fields,
        customer_profile=customer_profile,
    )

    match_score       = float(cross.get("match_score", 0.0))
    integrity_verdict = cross.get("integrity_verdict", "unknown")
    recommendation    = cross.get("recommendation", "review")
    confirmed_number  = cross.get("cross_verified_number") or qr_number

    log.info(
        "  Cross-match: score=%.0f%% integrity=%s recommendation=%s",
        match_score * 100, integrity_verdict, recommendation,
    )

    enriched = dict(groq_doc)

    if integrity_verdict == "major_discrepancy" or recommendation == "reject":
        enriched["_qr_used"]          = False
        enriched["_qr_fallback_note"] = (
            f"HF QR cross-match FAILED ({integrity_verdict}). "
            f"QR data does not match visual document. "
            + cross.get("cross_match_notes", "")
        )
        enriched["_hf_method"] = qr_result.get("decode_method", "opencv") + "+cross_fail"
        # Inject tampering flag
        existing_di = enriched.get("document_integrity", {})
        existing_issues = list(existing_di.get("integrity_issues") or [])
        existing_issues.append("HF QR-visual cross-match failed — possible tampering")
        mismatches = cross.get("mismatched_fields", [])
        for m in mismatches:
            if m.get("severity") == "critical":
                existing_issues.append(
                    f"Critical mismatch [{m['field']}]: "
                    f"visual='{m.get('visual_value')}' vs qr='{m.get('qr_value')}'"
                )
        enriched["document_integrity"] = {
            **existing_di,
            "integrity_issues": existing_issues,
            "integrity_score":  min(float(existing_di.get("integrity_score", 0.5)) * 0.4, 0.3),
            "appears_genuine":  False,
        }
    else:
        # Cross-match passed → inject QR document number
        enriched["_qr_used"]          = True
        enriched["_qr_fallback_note"] = (
            f"Document number recovered via HF OpenCV QR decode "
            f"({qr_result.get('qr_type', 'QR')}). "
            f"Cross-match: {integrity_verdict} ({match_score:.0%}). "
            + cross.get("cross_match_notes", "")
        )
        enriched["_hf_method"] = qr_result.get("decode_method", "opencv") + "+cross_ok"

        ef_updated = dict(ef)
        ef_updated["document_number"] = confirmed_number
        # Merge any QR fields that supplement empty visual fields
        for key, val in qr_all_fields.items():
            if not _null_or_empty(val) and _null_or_empty(ef_updated.get(key)):
                ef_updated[key] = val
        enriched["extracted_fields"] = ef_updated

        existing_di = enriched.get("document_integrity", {})
        enriched["document_integrity"] = {
            **existing_di,
            "integrity_score": min(float(existing_di.get("integrity_score", 0.7)) + 0.1, 0.95),
        }

    enriched["_qr_scan"]        = {
        "qr_found":           qr_result.get("qr_found", False),
        "qr_type":            qr_result.get("qr_type", ""),
        "qr_document_number": qr_number,
        "scan_confidence":    match_score,
        "scan_notes":         (
            f"OpenCV {qr_result.get('decode_method', '')} | "
            + cross.get("cross_match_notes", "")
        ),
    }
    enriched["_qr_cross_match"] = cross
    if trocr_result:
        enriched["_trocr_result"] = {
            "available":  trocr_result.get("trocr_available", False),
            "line_count": trocr_result.get("line_count", 0),
            "text_lines": trocr_result.get("text_lines", [])[:5],  # first 5 lines only
        }
    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — XGBoost evaluation per document
# ─────────────────────────────────────────────────────────────────────────────

def _evaluate_document(
    doc: dict,
    customer_name: str,
    groq_doc: dict | None,
) -> dict[str, Any]:
    """
    Run XGBoost type + validity classification using the fully enriched
    groq_doc (which may have been augmented by Stage 1b QR fallback).
    """
    text    = doc.get("text_content", "")
    fname   = doc.get("original_filename", "")
    is_img  = doc.get("is_image", False)
    method  = doc.get("extraction_method", "none")
    evid_id = doc.get("evidence_id", "")

    ml = classify_document(
        text_content=text,
        filename=fname,
        is_image=is_img,
        extraction_method=method,
        customer_name=customer_name,
        groq_fields=groq_doc,
    )

    doc_type      = ml.get("doc_type", "unknown")
    type_conf     = ml.get("doc_type_confidence", 0.0)
    validity_conf = ml.get("validity_confidence", 0.0)
    is_valid_ml   = ml.get("is_valid", False)
    issues        = list(ml.get("validity_issues", []))
    kyc_purpose   = ml.get("kyc_purpose", {"poi": False, "poa": False})
    completeness  = ml.get("completeness_score", 0.0)
    trust         = ml.get("trust_signal_score", 0.0)
    doc_number    = ml.get("doc_number", "")
    ml_used       = ml.get("ml_used", False)
    groq_fields_extracted = ml.get("groq_extracted_fields", {})
    # Prefer Groq-extracted number when ML regex missed it (common on image Aadhaar)
    groq_doc_num = (groq_doc or {}).get("extracted_fields", {}).get("document_number")
    if groq_doc_num and not doc_number:
        doc_number = str(groq_doc_num).replace(" ", "").strip()
    elif groq_doc_num and doc_number:
        groq_clean = str(groq_doc_num).replace(" ", "").strip()
        if groq_clean and groq_clean != doc_number:
            issues.append(
                f"ML extracted number ({doc_number}) differs from Groq Vision ({groq_clean})"
            )

    # Pull QR metadata if Stage 1b ran
    qr_used   = bool((groq_doc or {}).get("_qr_used", False))
    qr_note   = (groq_doc or {}).get("_qr_fallback_note", "")
    qr_scan   = (groq_doc or {}).get("_qr_scan", {})
    qr_cross  = (groq_doc or {}).get("_qr_cross_match", {})

    # ── Verdict logic ─────────────────────────────────────────────────────────
    if not ml_used:
        verdict = "NEEDS_REVIEW"
        verdict_reason = "ML classifier unavailable — manual review required"

    elif doc_type == "unknown" or type_conf < NEEDS_REVIEW_TYPE:
        verdict = "REJECTED"
        verdict_reason = (
            f"Could not identify a valid Indian KYC document "
            f"(type confidence {type_conf:.0%})"
        )

    elif not is_valid_ml:
        if validity_conf >= VERIFIED_VALIDITY_CONF:
            feats = ml.get("features_extracted", {})
            has_good_number  = feats.get("doc_number_format_ok", 0)
            has_name         = feats.get("has_name", 0)
            has_photo_feat   = feats.get("has_photo", 0)
            groq_integrity   = (groq_doc or {}).get("document_integrity", {})
            groq_score       = float(groq_integrity.get("integrity_score", 0.5))
            groq_appears_ok  = groq_integrity.get("appears_genuine", False)

            # Classify each issue as structural (hard) or soft (formatting/limitation)
            SOFT_KEYWORDS = (
                "photograph", "photo",
                "address not found",
                "[groq] no visible signs",
                "dob mismatch", "date of birth mismatch",
                "profile mismatch",
                "physical document inspection",
                "year",
                "document number format invalid",  # DL formats vary by state
            )
            structural_issues = [
                i for i in issues
                if not any(kw in i.lower() for kw in SOFT_KEYWORDS)
            ]
            soft_issues = [i for i in issues if i not in structural_issues]

            # DL with Groq-confirmed photo + valid expiry → treat expiry/photo text issues as soft
            groq_ef = (groq_doc or {}).get("extracted_fields", {})
            groq_photo = groq_ef.get("photo_present") is True
            if doc_type == "driving_licence" and groq_photo:
                structural_issues = [
                    i for i in structural_issues
                    if "expired" not in i.lower() and "photograph" not in i.lower()
                ]
                soft_issues = [i for i in issues if i not in structural_issues]

            # Case A: Only photo issue from text-extracted PDF (no image data)
            photo_only = (
                len(structural_issues) == 0
                and any("photograph" in i.lower() for i in issues)
                and not is_img
            )

            # Case B: Image/vision doc — Groq Vision extracted core fields successfully.
            image_core_verified = (
                (is_img or bool((groq_doc or {}).get("_extraction_method") == "vision"))
                and has_good_number
                and has_name
                and (has_photo_feat or groq_photo)
                and len(structural_issues) == 0
                and groq_appears_ok
            )

            # Case C: Text PDF driving licence — core fields from Groq text + valid number
            pdf_dl_verified = (
                doc_type == "driving_licence"
                and method == "pypdf"
                and has_good_number
                and has_name
                and len(structural_issues) == 0
                and groq_appears_ok
            )

            if photo_only:
                verdict = "NEEDS_REVIEW"
                verdict_reason = (
                    f"{DOC_DISPLAY.get(doc_type, doc_type)} structurally valid "
                    f"(type {type_conf:.0%}) — photograph could not be verified "
                    f"from text extraction; physical inspection required"
                )
                issues = [
                    "Photograph verification requires physical document inspection "
                    "(not detectable from text-extracted PDF)"
                ]

            elif image_core_verified and groq_score >= 0.75:
                # Groq Vision confirms all critical fields — VERIFIED
                verdict = "VERIFIED"
                verdict_reason = (
                    f"{DOC_DISPLAY.get(doc_type, doc_type)} verified via Groq Vision "
                    f"(type {type_conf:.0%}, number ✓, name ✓, photo ✓, "
                    f"integrity {groq_score:.0%})"
                )
                if soft_issues:
                    verdict_reason += f" — minor notes: {'; '.join(soft_issues[:2])}"
                issues = soft_issues  # keep soft issues visible but not blocking

            elif image_core_verified:
                # Core fields verified but integrity score is moderate
                verdict = "NEEDS_REVIEW"
                verdict_reason = (
                    f"{DOC_DISPLAY.get(doc_type, doc_type)} core fields confirmed "
                    f"(type {type_conf:.0%}, number ✓, name ✓, photo ✓) — "
                    f"integrity {groq_score:.0%}, minor issues flagged for review"
                )
                issues = soft_issues

            elif pdf_dl_verified and groq_score >= 0.65:
                verdict = "VERIFIED"
                verdict_reason = (
                    f"Driving Licence verified from PDF "
                    f"(type {type_conf:.0%}, number ✓, name ✓, integrity {groq_score:.0%})"
                )
                issues = soft_issues

            elif pdf_dl_verified:
                verdict = "NEEDS_REVIEW"
                verdict_reason = (
                    f"Driving Licence fields extracted from PDF — manual review recommended "
                    f"(integrity {groq_score:.0%})"
                )
                issues = soft_issues

            else:
                verdict = "REJECTED"
                verdict_reason = (
                    f"Document failed Indian KYC structural validation "
                    f"({validity_conf:.0%} confidence of invalidity)"
                )
        else:
            verdict = "NEEDS_REVIEW"
            verdict_reason = (
                f"Document validation inconclusive "
                f"(validity confidence {validity_conf:.0%}) — manual review required"
            )

    else:
        # is_valid_ml = True
        if type_conf < VERIFIED_TYPE_CONF or validity_conf < VERIFIED_VALIDITY_CONF:
            verdict = "NEEDS_REVIEW"
            verdict_reason = (
                f"Document likely valid but below confidence threshold "
                f"(type {type_conf:.0%}, validity {validity_conf:.0%})"
            )
        else:
            verdict = "VERIFIED"
            verdict_reason = (
                f"{DOC_DISPLAY.get(doc_type, doc_type)} verified successfully "
                f"(type {type_conf:.0%}, validity {validity_conf:.0%})"
            )
            if qr_used:
                verdict_reason += " [document number recovered and confirmed via QR cross-match]"

    return {
        "evidence_id":            evid_id,
        "filename":               fname,
        "doc_type":               doc_type,
        "doc_type_display":       DOC_DISPLAY.get(doc_type, doc_type),
        "doc_type_confidence":    round(type_conf, 4),
        "doc_number":             doc_number,
        "is_valid_ml":            is_valid_ml,
        "validity_confidence":    round(validity_conf, 4),
        "verdict":                verdict,
        "verdict_reason":         verdict_reason,
        "validity_issues":        issues,
        "kyc_purpose":            kyc_purpose,
        "completeness_score":     round(completeness, 3),
        "trust_signal_score":     round(trust, 3),
        "all_type_probabilities": ml.get("all_type_probabilities", {}),
        "ml_used":                ml_used,
        "groq_extracted_fields":  groq_fields_extracted,
        "groq_doc_type_hint":     (groq_doc or {}).get("detected_doc_type", ""),
        "groq_integrity_score":   (groq_doc or {}).get("document_integrity", {}).get("integrity_score"),
        "groq_notes":             (groq_doc or {}).get("groq_notes", ""),
        "groq_profile_match":     (groq_doc or {}).get("profile_match", {}),
        # QR fallback metadata
        "qr_fallback_used":       qr_used,
        "qr_fallback_note":       qr_note,
        "qr_scan_result":         {
            "qr_found":           qr_scan.get("qr_found", False),
            "qr_type":            qr_scan.get("qr_type", ""),
            "qr_document_number": qr_scan.get("qr_document_number"),
            "scan_confidence":    qr_scan.get("scan_confidence", 0.0),
            "scan_notes":         qr_scan.get("scan_notes", ""),
        } if qr_scan else None,
        "qr_cross_match_result":  {
            "fields_match":       qr_cross.get("fields_match"),
            "match_score":        qr_cross.get("match_score"),
            "matched_fields":     qr_cross.get("matched_fields", []),
            "mismatched_fields":  qr_cross.get("mismatched_fields", []),
            "integrity_verdict":  qr_cross.get("integrity_verdict"),
            "recommendation":     qr_cross.get("recommendation"),
            "cross_match_notes":  qr_cross.get("cross_match_notes", ""),
        } if qr_cross else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate case-level verdict
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_verdict(
    evaluations: list[dict[str, Any]],
) -> tuple[str, str, list[str]]:
    """Returns (verdict, summary, rejection_reasons)."""

    if not evaluations:
        return (
            "REJECTED",
            "No documents uploaded. Valid Indian KYC proof is mandatory.",
            ["No documents uploaded"],
        )

    verified_docs = [e for e in evaluations if e["verdict"] == "VERIFIED"]
    review_docs   = [e for e in evaluations if e["verdict"] == "NEEDS_REVIEW"]
    rejected_docs = [e for e in evaluations if e["verdict"] == "REJECTED"]

    has_poi = any(e["kyc_purpose"].get("poi") for e in verified_docs)
    has_poa = any(e["kyc_purpose"].get("poa") for e in verified_docs)

    rejection_reasons: list[str] = []
    for e in rejected_docs:
        rejection_reasons.append(f"{e['filename']}: {e['verdict_reason']}")
        for issue in e["validity_issues"][:3]:
            if not issue.startswith("[Groq]"):
                rejection_reasons.append(f"  └ {issue}")

    if not verified_docs and not review_docs:
        return (
            "REJECTED",
            (
                f"All {len(evaluations)} uploaded document(s) failed Indian KYC verification. "
                "No valid Aadhaar / PAN / Passport / Voter ID / "
                "Driving Licence / Bank Passbook could be confirmed."
            ),
            rejection_reasons,
        )

    if not verified_docs:
        review_types = [DOC_DISPLAY.get(e["doc_type"], e["doc_type"]) for e in review_docs]
        return (
            "NEEDS_REVIEW",
            (
                f"Documents require manual review: {', '.join(review_types)}. "
                "Automatic verification could not be completed with sufficient confidence."
            ),
            rejection_reasons,
        )

    if REQUIRE_POI and not has_poi:
        verified_names = [DOC_DISPLAY.get(e["doc_type"], e["doc_type"]) for e in verified_docs]
        rejection_reasons.insert(
            0,
            "No valid Proof of Identity (POI) document found. "
            "Aadhaar / PAN / Passport / Voter ID / Driving Licence required.",
        )
        return (
            "REJECTED",
            (
                f"POI requirement not satisfied. Verified document(s) "
                f"({', '.join(verified_names)}) do not qualify as POI "
                "under RBI KYC Master Directions."
            ),
            rejection_reasons,
        )

    if REQUIRE_POA and not has_poa:
        rejection_reasons.insert(
            0,
            "No valid Proof of Address (POA) document found. "
            "Aadhaar / Passport / Voter ID / Driving Licence / Bank Passbook required.",
        )
        return ("REJECTED", "POA requirement not satisfied.", rejection_reasons)

    verified_types = [DOC_DISPLAY.get(e["doc_type"], e["doc_type"]) for e in verified_docs]
    purpose_parts  = (["✓ POI"] if has_poi else []) + (["✓ POA"] if has_poa else [])
    purpose_str    = " | ".join(purpose_parts)

    # Note which docs used QR fallback
    qr_recovered = [e for e in verified_docs if e.get("qr_fallback_used")]
    qr_note_str  = f" (QR-recovered: {', '.join(e['filename'] for e in qr_recovered)})" if qr_recovered else ""

    if rejected_docs:
        return (
            "NEEDS_REVIEW",
            (
                f"{len(verified_docs)} document(s) verified ({', '.join(verified_types)}) "
                f"[{purpose_str}]{qr_note_str}. {len(rejected_docs)} document(s) rejected."
            ),
            rejection_reasons,
        )

    return (
        "VERIFIED",
        (
            f"All {len(verified_docs)} document(s) verified: "
            f"{', '.join(verified_types)} [{purpose_str}]{qr_note_str}."
        ),
        [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main agent
# ─────────────────────────────────────────────────────────────────────────────

def indian_document_verification_agent(state: KYCState) -> KYCState:
    """
    Stage 1  : Groq extracts fields from every uploaded document.
    Stage 1b : If document number missing but QR detected → Groq
               scans QR payload, then cross-matches QR vs text.
               Matching QR → number accepted. Mismatch → tamper flag.
    Stage 2  : XGBoost classifies type + validates each document
               using the fully enriched feature vector.
    """
    evidence_ids  = state.customer_profile.get("evidence_ids", [])
    uploaded      = state.uploaded_evidence or get_evidence(evidence_ids)
    customer_name = state.customer_profile.get("name", "")
    declared_id   = state.customer_profile.get("id_number", "")
    # Document type the customer declared on the intake form (e.g. "PAN Card").
    declared_doc_type = state.customer_profile.get("document_type", "")

    # ── Stage 1: Groq field extraction ───────────────────────────────────────
    groq_map:    dict[str, dict] = {}
    groq_overall = ""
    qr_fallback_docs: list[str] = []

    if uploaded:
        log.info(
            "Doc Verification Stage 1 — Groq extracting fields from %d doc(s)",
            len(uploaded),
        )
        groq_map = _run_groq_extraction(uploaded, state.customer_profile)
        groq_overall = "Groq extracted fields from %d/%d document(s)" % (
            len(groq_map), len(uploaded)
        )
        log.info(groq_overall)

        # ── Stage 1b: QR fallback for docs with no number but QR present ─────
        for doc in uploaded:
            fname    = doc.get("original_filename", "")
            groq_doc = groq_map.get(fname)
            if groq_doc is None:
                continue

            ef           = groq_doc.get("extracted_fields", {})
            doc_number   = ef.get("document_number")
            qr_present   = ef.get("qr_or_barcode_present", False)
            mrz_present  = ef.get("mrz_present", False)
            has_no_number = _null_or_empty(doc_number)

            if has_no_number and (qr_present or mrz_present):
                log.info(
                    "  Stage 1b: '%s' — no doc number found, QR/MRZ detected → running QR fallback",
                    fname,
                )
                enriched_groq_doc = _run_qr_fallback(doc, groq_doc, state.customer_profile)
                groq_map[fname]   = enriched_groq_doc
                qr_fallback_docs.append(fname)
            else:
                if has_no_number:
                    log.info(
                        "  Stage 1b: '%s' — no doc number, no QR detected — proceeding without QR",
                        fname,
                    )

        if qr_fallback_docs:
            log.info(
                "Stage 1b complete — QR fallback ran for: %s",
                ", ".join(qr_fallback_docs),
            )
    else:
        log.info("Doc Verification — no documents uploaded")

    # ── Stage 2: XGBoost classification ──────────────────────────────────────
    log.info("Doc Verification Stage 2 — XGBoost ML classification")
    from app.services.id_cross_check import (
        extract_dl_number_from_text,
        find_declared_dl_in_text,
        is_dl_format,
        is_plausible_dl_number,
        normalize_dl_id,
    )

    evaluations: list[dict[str, Any]] = []
    for doc in uploaded:
        fname    = doc.get("original_filename", "")
        groq_doc = groq_map.get(fname)
        evaluation = _evaluate_document(doc, customer_name, groq_doc)

        # Driving licence: canonical ID is the DL No printed on the document
        if evaluation.get("doc_type") == "driving_licence":
            text = doc.get("text_content", "") or ""
            evaluation["text_content"] = text
            dl_no = extract_dl_number_from_text(text, declared_id=declared_id)
            if not dl_no and groq_doc:
                groq_num = str(
                    (groq_doc.get("extracted_fields") or {}).get("document_number") or ""
                ).strip()
                if is_plausible_dl_number(groq_num):
                    dl_no = groq_num
                elif (
                    (groq_doc.get("profile_match") or {}).get("id_number_matches") is True
                    and declared_id
                    and is_dl_format(declared_id)
                ):
                    dl_no = declared_id.strip().upper()
            if dl_no and not is_plausible_dl_number(dl_no):
                dl_no = find_declared_dl_in_text(declared_id, text) if declared_id else ""
            if dl_no:
                evaluation["dl_number_from_label"] = dl_no
                evaluation["doc_number"] = normalize_dl_id(dl_no) if dl_no else evaluation.get("doc_number")
                gf = evaluation.setdefault("groq_extracted_fields", {})
                gf["document_number"] = dl_no
                if groq_doc:
                    groq_doc.setdefault("extracted_fields", {})["document_number"] = dl_no
            else:
                existing = str(evaluation.get("doc_number") or "")
                if existing and not is_plausible_dl_number(existing):
                    evaluation["doc_number"] = ""
                gf = dict(evaluation.get("groq_extracted_fields") or {})
                gnum = str(gf.get("document_number") or "")
                if gnum and not is_plausible_dl_number(gnum):
                    gf["document_number"] = None
                    evaluation["groq_extracted_fields"] = gf

            from app.services.name_cross_check import extract_name_from_dl_text

            doc_name = extract_name_from_dl_text(text)
            if not doc_name and groq_doc:
                doc_name = str(
                    (groq_doc.get("extracted_fields") or {}).get("full_name") or ""
                ).strip()
            if doc_name and doc_name.lower() not in ("null", "none", ""):
                evaluation["name_from_document"] = doc_name.strip().upper()
                gf = evaluation.setdefault("groq_extracted_fields", {})
                if not gf.get("full_name"):
                    gf["full_name"] = doc_name.strip().upper()

        evaluations.append(evaluation)
        log.debug(
            "  '%s' → type=%s (%.0f%%) verdict=%s [groq=%s, qr=%s]",
            fname,
            evaluation["doc_type"],
            evaluation["doc_type_confidence"] * 100,
            evaluation["verdict"],
            "yes" if groq_doc else "no",
            "yes" if evaluation.get("qr_fallback_used") else "no",
        )

    # ── ID number cross-check (declared vs document) ──────────────────────────
    from app.services.id_cross_check import check_id_mismatch, normalize_id
    from app.services.name_cross_check import check_name_mismatch

    id_mismatch = check_id_mismatch(declared_id, {"per_document": evaluations})
    name_mismatch = check_name_mismatch(customer_name, {"per_document": evaluations})

    if id_mismatch:
        log.warning(
            "ID mismatch: declared=%s extracted=%s",
            id_mismatch["declared"], id_mismatch["extracted"],
        )
        for ev in evaluations:
            ev["id_mismatch"] = True
            ev["id_mismatch_detail"] = id_mismatch
            if ev.get("verdict") == "VERIFIED":
                ev["verdict"] = "NEEDS_REVIEW"
                ev["verdict_reason"] = (
                    f"Document verified but entered ID ({normalize_id(declared_id)}) "
                    f"does not match document number ({id_mismatch['extracted']})"
                )
                ev["validity_issues"] = list(ev.get("validity_issues", [])) + [
                    id_mismatch["short_reason"]
                ]

    if name_mismatch:
        log.warning(
            "Name mismatch on DL: declared=%s extracted=%s",
            name_mismatch["declared"], name_mismatch["extracted"],
        )
        for ev in evaluations:
            if ev.get("doc_type") != "driving_licence":
                continue
            ev["name_mismatch"] = True
            ev["name_mismatch_detail"] = name_mismatch
            if ev.get("verdict") == "VERIFIED":
                ev["verdict"] = "NEEDS_REVIEW"
                ev["verdict_reason"] = (
                    f"Driving licence verified but entered name ({name_mismatch['declared']}) "
                    f"does not match name on document ({name_mismatch['extracted']})"
                )
                ev["validity_issues"] = list(ev.get("validity_issues", [])) + [
                    name_mismatch["short_reason"]
                ]

    # ── Declared vs detected document-type consistency ────────────────────────
    from app.services.doc_type_match import check_doc_type_mismatch

    doc_type_match = check_doc_type_mismatch(declared_doc_type, evaluations)
    if doc_type_match.get("document_type_mismatch"):
        log.warning(
            "Document type mismatch: declared=%s detected=%s severity=%s",
            doc_type_match["declared_doc_type"],
            doc_type_match["detected_doc_type"],
            doc_type_match["mismatch_severity"],
        )

    # ── Aggregate ─────────────────────────────────────────────────────────────
    verdict, summary, rejection_reasons = _aggregate_verdict(evaluations)

    if id_mismatch:
        rejection_reasons.insert(0, id_mismatch["reason"])
        if verdict == "VERIFIED":
            verdict = "NEEDS_REVIEW"
            summary = (
                f"Documents structurally valid but ID number mismatch: "
                f"entered {id_mismatch['declared']} vs document {id_mismatch['extracted']}"
            )

    if name_mismatch:
        rejection_reasons.insert(0, name_mismatch["reason"])
        if verdict == "VERIFIED":
            verdict = "NEEDS_REVIEW"
            summary = (
                f"Documents structurally valid but name mismatch on driving licence: "
                f"entered {name_mismatch['declared']} vs document {name_mismatch['extracted']}"
            )

    verified_count = sum(1 for e in evaluations if e["verdict"] == "VERIFIED")
    rejected_count = sum(1 for e in evaluations if e["verdict"] == "REJECTED")
    review_count   = sum(1 for e in evaluations if e["verdict"] == "NEEDS_REVIEW")
    qr_used_count  = sum(1 for e in evaluations if e.get("qr_fallback_used"))

    has_poi = any(e["kyc_purpose"].get("poi") for e in evaluations if e["verdict"] == "VERIFIED")
    has_poa = any(e["kyc_purpose"].get("poa") for e in evaluations if e["verdict"] == "VERIFIED")
    verified_types = [e["doc_type_display"] for e in evaluations if e["verdict"] == "VERIFIED"]

    state.document_verdict = {
        "verdict":                verdict,
        "summary":                summary,
        "declared_doc_type":      declared_doc_type,
        "detected_doc_type":      doc_type_match.get("detected_doc_type", ""),
        "document_type_mismatch": doc_type_match.get("document_type_mismatch", False),
        "mismatch_severity":      doc_type_match.get("mismatch_severity", "NONE"),
        "doc_type_match":         doc_type_match,
        "rejection_reasons":      rejection_reasons,
        "verified_count":         verified_count,
        "rejected_count":         rejected_count,
        "review_count":           review_count,
        "total_docs":             len(evaluations),
        "has_poi":                has_poi,
        "has_poa":                has_poa,
        "verified_types":         verified_types,
        "per_document":           evaluations,
        "pipeline_blocked":       verdict == "REJECTED",
        "groq_extraction_summary": groq_overall,
        "groq_docs_extracted":    len(groq_map),
        "qr_fallback_docs":       qr_fallback_docs,
        "qr_fallback_count":      qr_used_count,
        "id_mismatch":            id_mismatch,
        "name_mismatch":          name_mismatch,
    }

    state.workflow_path.append("indian_document_verification")

    # ── REJECTED → short-circuit pipeline ────────────────────────────────────
    if verdict == "REJECTED":
        state.risk_assessment = {
            "risk_score":      100,
            "risk_level":      "High",
            "breakdown": [{
                "signal": "Document Verification REJECTED",
                "points": 100,
                "source": "document_verification",
            }],
            "scoring_method": "document_rejection",
            "rule_score":      100,
        }
        narrative = (
            f"DOCUMENT REJECTED\n\n{summary}\n\n"
            + (
                "Rejection details:\n"
                + "\n".join(f"• {r}" for r in rejection_reasons)
                if rejection_reasons else ""
            )
        )
        reject_reasons = ["Document verification failed — " + r for r in rejection_reasons[:5]]
        if doc_type_match.get("document_type_mismatch"):
            reject_reasons.insert(0, doc_type_match["reason"])
        state.explanation = {
            "decision_hint": "ESCALATE",
            "reasons":       reject_reasons,
            "narrative":     narrative,
            "risk_level":    "High",
            "risk_score":    100,
            "document_type_mismatch": doc_type_match,
        }
        state.decision = {
            "status":                "ESCALATE",
            "risk_score":            100,
            "risk_level":            "High",
            "requires_human_review": True,
            "auto_decision":         False,
            "document_rejected":     True,
            "rejection_reasons":     rejection_reasons,
            "reasons":               state.explanation["reasons"],
        }
        log_event(
            state,
            "Indian Document Verification Agent",
            f"REJECTED — {summary}",
            {
                "stage1_groq":       groq_overall,
                "stage1b_qr":        f"QR fallback ran for {len(qr_fallback_docs)} doc(s)",
                "stage2_xgboost":    "classification complete",
                "verdict":           verdict,
                "rejection_reasons": rejection_reasons,
                "total_docs":        len(evaluations),
                "rejected_count":    rejected_count,
            },
        )
    else:
        log_event(
            state,
            "Indian Document Verification Agent",
            f"{verdict} — {summary}",
            {
                "stage1_groq":    groq_overall,
                "stage1b_qr":     f"QR fallback: {qr_used_count} doc(s) recovered via QR",
                "stage2_xgboost": "classification complete",
                "verdict":        verdict,
                "verified_count": verified_count,
                "has_poi":        has_poi,
                "has_poa":        has_poa,
                "verified_types": verified_types,
            },
        )

    return state
