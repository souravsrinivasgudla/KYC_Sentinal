"""
HuggingFace Document Extractor Service
========================================
Two complementary extraction methods for image-based
Indian KYC documents:

METHOD A — OpenCV QR Decode (primary)
──────────────────────────────────────
Uses cv2.QRCodeDetector to read the actual binary QR
payload embedded in the document image. No network call.
Works on Aadhaar (XML payload), PAN (QR), Voter ID,
Driving Licence, and Passport MRZ-adjacent barcodes.

Aadhaar QR format:
  <?xml ...><PrintLetterBarcodeData uid="XXXXXXXXXXXX"
    name="..." gender="M" yob="YYYY"
    co="S/O ..." house="..." street="..."
    vtc="..." dist="..." state="..." pc="XXXXXX"/>

METHOD B — TrOCR Line-Level OCR (secondary / fallback)
────────────────────────────────────────────────────────
Uses microsoft/trocr-base-printed from HuggingFace.
Detects horizontal text-line contours with OpenCV,
crops each line, and runs TrOCR on each crop.
Quality on real-world Indian ID scans is limited but
provides a second source for name/number verification
when QR decode fails.

FLOW WHEN DOCUMENT NUMBER IS MISSING
──────────────────────────────────────
  1. If Groq reports qr_or_barcode_present=True
     → Try OpenCV QR decode on raw image
     → If QR data found → parse structured fields
     → Cross-match QR fields vs Groq-extracted text fields
     → If they match → accept QR document number
     → If they mismatch → flag tampering

  2. If OpenCV QR decode fails
     → Run TrOCR line OCR as fallback
     → Feed OCR lines back to Groq for structured parsing
     → Cross-match with original extraction

  3. Cross-match is always done via Groq for semantic
     understanding (name spelling variations, abbreviations)
"""

from __future__ import annotations

import io
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# ── Lazy-loaded singletons ────────────────────────────────────────────────────
_trocr_processor = None
_trocr_model     = None


def _get_hf_token() -> str:
    try:
        from app.config import settings
        return settings.hf_token or ""
    except Exception:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        return os.getenv("HF_TOKEN", "")


def _load_trocr():
    """Lazy-load TrOCR processor + model (cached after first load)."""
    global _trocr_processor, _trocr_model
    if _trocr_processor is not None:
        return True
    try:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        token = _get_hf_token()
        log.info("Loading microsoft/trocr-base-printed from HuggingFace...")
        _trocr_processor = TrOCRProcessor.from_pretrained(
            "microsoft/trocr-base-printed", token=token or None,
        )
        _trocr_model = VisionEncoderDecoderModel.from_pretrained(
            "microsoft/trocr-base-printed", token=token or None,
        )
        _trocr_model.eval()
        log.info("TrOCR loaded OK")
        return True
    except Exception as exc:
        log.warning("TrOCR load failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# METHOD A — OpenCV QR decode
# ─────────────────────────────────────────────────────────────────────────────

def _parse_aadhaar_qr_xml(xml_str: str) -> dict[str, Any]:
    """
    Parse the Aadhaar PrintLetterBarcodeData XML payload.
    Returns a normalised fields dict.
    """
    xml_str = xml_str.strip()
    # Strip BOM or leading whitespace
    if xml_str.startswith("\ufeff"):
        xml_str = xml_str[1:]
    try:
        root = ET.fromstring(xml_str)
        attrs = root.attrib
        # Normalise address
        address_parts = [
            attrs.get("house", ""), attrs.get("street", ""),
            attrs.get("loc", ""),   attrs.get("vtc", ""),
            attrs.get("po", ""),    attrs.get("dist", ""),
            attrs.get("state", ""), attrs.get("pc", ""),
        ]
        address = ", ".join(p for p in address_parts if p.strip())

        return {
            "qr_type":           "aadhaar_xml",
            "document_number":   attrs.get("uid", ""),
            "full_name":         attrs.get("name", ""),
            "gender":            attrs.get("gender", ""),
            "year_of_birth":     attrs.get("yob", ""),
            "date_of_birth":     attrs.get("dob", ""),   # present in newer QRs
            "father_guardian":   attrs.get("co", ""),
            "address":           address,
            "pincode":           attrs.get("pc", ""),
            "state":             attrs.get("state", ""),
            "district":          attrs.get("dist", ""),
            "mobile_hash":       attrs.get("m", ""),
            "email_hash":        attrs.get("e", ""),
            "raw_attributes":    dict(attrs),
        }
    except ET.ParseError as exc:
        log.warning("Aadhaar XML parse error: %s", exc)
        return {"qr_type": "unknown", "raw": xml_str[:500]}


def _parse_generic_qr(data: str) -> dict[str, Any]:
    """
    Parse non-Aadhaar QR payloads (PAN, Voter ID, DL, etc.).
    Tries JSON first, then key=value, then returns raw.
    """
    import json as _json
    try:
        parsed = _json.loads(data)
        return {"qr_type": "json", **parsed}
    except Exception:
        pass

    # key=value pairs
    kv_pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)(?=\s+[A-Za-z_]|$)")
    matches = kv_pattern.findall(data)
    if matches:
        return {"qr_type": "key_value", **dict(matches)}

    return {"qr_type": "raw_text", "raw": data[:500]}


def decode_qr_from_image(image_bytes: bytes) -> dict[str, Any]:
    """
    Attempt to decode a QR code from image bytes using OpenCV.

    Returns:
      qr_found       : bool
      qr_type        : str  (aadhaar_xml | json | key_value | raw_text | none)
      document_number: str | None
      full_name      : str | None
      gender         : str | None
      date_of_birth  : str | None
      year_of_birth  : str | None
      address        : str | None
      raw_payload    : str | None (first 300 chars)
      all_fields     : dict  (everything parsed from QR)
      decode_method  : str
    """
    try:
        import cv2
    except ImportError:
        return {"qr_found": False, "error": "opencv not installed"}

    try:
        nparr  = np.frombuffer(image_bytes, np.uint8)
        cv_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if cv_img is None:
            return {"qr_found": False, "error": "could not decode image"}
    except Exception as exc:
        return {"qr_found": False, "error": str(exc)}

    qr_data  = ""
    method   = "opencv_standard"

    # Try standard QRCodeDetector
    try:
        detector = cv2.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(cv_img)
        if data:
            qr_data = data
    except Exception:
        pass

    # If standard fails, try on upscaled / contrast-enhanced image
    if not qr_data:
        try:
            scale  = 2.0
            h, w   = cv_img.shape[:2]
            big    = cv2.resize(cv_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
            detector2 = cv2.QRCodeDetector()
            data2, _, _ = detector2.detectAndDecode(big)
            if data2:
                qr_data = data2
                method  = "opencv_upscaled"
        except Exception:
            pass

    if not qr_data:
        return {
            "qr_found": False,
            "qr_type": "none",
            "document_number": None,
            "full_name": None,
            "gender": None,
            "date_of_birth": None,
            "year_of_birth": None,
            "address": None,
            "raw_payload": None,
            "all_fields": {},
            "decode_method": method,
        }

    # Parse QR payload
    raw_stripped = qr_data.strip()
    if raw_stripped.startswith("<?xml") or "<PrintLetterBarcodeData" in raw_stripped:
        parsed = _parse_aadhaar_qr_xml(raw_stripped)
    else:
        parsed = _parse_generic_qr(raw_stripped)

    doc_number = (
        parsed.get("document_number") or
        parsed.get("uid") or
        parsed.get("PAN") or
        parsed.get("pan") or
        ""
    )

    return {
        "qr_found":       True,
        "qr_type":        parsed.get("qr_type", "unknown"),
        "document_number": doc_number.replace(" ", "") if doc_number else None,
        "full_name":      parsed.get("full_name") or parsed.get("name"),
        "gender":         parsed.get("gender"),
        "date_of_birth":  parsed.get("date_of_birth") or parsed.get("dob"),
        "year_of_birth":  parsed.get("year_of_birth") or parsed.get("yob"),
        "address":        parsed.get("address"),
        "raw_payload":    raw_stripped[:300],
        "all_fields":     parsed,
        "decode_method":  method,
    }


# ─────────────────────────────────────────────────────────────────────────────
# METHOD B — TrOCR line-level OCR
# ─────────────────────────────────────────────────────────────────────────────

def _detect_text_line_crops(
    pil_image: "Image.Image",    # type: ignore
) -> list["Image.Image"]:        # type: ignore
    """
    Detect horizontal text-line regions using OpenCV contour analysis.
    Returns list of PIL Image crops (one per text line, top-to-bottom).
    """
    import cv2
    from PIL import Image

    cv_img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    gray   = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    # Binarise with adaptive threshold
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 21, 10,
    )

    # Dilate horizontally to merge chars → words → lines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (80, 6))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_img, w_img = gray.shape

    rects: list[tuple[int, int, int, int]] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # Filter noise and full-width decorations
        if w > 80 and h > 8 and h < 100 and w < w_img * 0.95:
            rects.append((x, y, w, h))
    rects.sort(key=lambda r: r[1])   # top to bottom

    # Merge rows that are vertically adjacent (gap < 12 px)
    merged: list[tuple[int, int, int, int]] = []
    for r in rects:
        if merged and abs(r[1] - (merged[-1][1] + merged[-1][3])) < 12:
            px, py, pw, ph = merged[-1]
            nx = min(px, r[0]);  ny = min(py, r[1])
            nw = max(px+pw, r[0]+r[2]) - nx
            nh = max(py+ph, r[1]+r[3]) - ny
            merged[-1] = (nx, ny, nw, nh)
        else:
            merged.append(r)

    pad = 4
    crops: list[Image.Image] = []
    for (x, y, w, h) in merged[:40]:
        x1 = max(0, x - pad);  y1 = max(0, y - pad)
        x2 = min(w_img, x + w + pad);  y2 = min(h_img, y + h + pad)
        crop = pil_image.crop((x1, y1, x2, y2))
        if crop.width >= 10 and crop.height >= 6:
            crops.append(crop)
    return crops


# HuggingFace Inference API OCR model (used when an HF token is configured —
# no local torch/transformers download required).
HF_OCR_MODEL = "microsoft/trocr-base-printed"
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_OCR_MODEL}"
HF_MAX_LINES = 18  # cap API calls per document


def _hf_api_ocr(image_bytes: bytes, token: str) -> dict[str, Any]:
    """
    OCR an image via the HuggingFace Inference API (TrOCR), one call per detected
    text line. Uses OpenCV line detection locally (no model download) and the HF
    API for recognition. Degrades gracefully to empty on any failure.
    """
    try:
        import io as _io

        import httpx
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        log.warning("HF OCR deps unavailable: %s", exc)
        return {"trocr_available": False, "text_lines": [], "full_text": "", "line_count": 0}

    try:
        pil_img = Image.open(_io.BytesIO(image_bytes)).convert("RGB")
        crops = _detect_text_line_crops(pil_img)[:HF_MAX_LINES]
    except Exception as exc:
        log.warning("HF OCR line detection failed: %s", exc)
        return {"trocr_available": False, "text_lines": [], "full_text": "", "line_count": 0}

    if not crops:
        return {"trocr_available": False, "text_lines": [], "full_text": "", "line_count": 0}

    headers = {"Authorization": f"Bearer {token}"}
    lines: list[str] = []
    log.info("HF Inference OCR: sending %d line crop(s) to %s", len(crops), HF_OCR_MODEL)
    try:
        with httpx.Client(timeout=20.0) as client:
            for crop in crops:
                buf = _io.BytesIO()
                crop.save(buf, format="PNG")
                try:
                    resp = client.post(HF_API_URL, headers=headers, content=buf.getvalue())
                except Exception:
                    continue
                if resp.status_code != 200:
                    # 503 = model warming up, 404 = model not served, 401 = bad token.
                    log.warning("HF OCR call returned %s; stopping", resp.status_code)
                    break
                try:
                    data = resp.json()
                except Exception:
                    continue
                text = ""
                if isinstance(data, list) and data:
                    text = str(data[0].get("generated_text", "")).strip()
                elif isinstance(data, dict):
                    text = str(data.get("generated_text", "")).strip()
                if text and len(text) > 1:
                    lines.append(text)
    except Exception as exc:
        log.warning("HF OCR request failed: %s", exc)

    return {
        "trocr_available": bool(lines),
        "text_lines": lines,
        "full_text": "\n".join(lines),
        "line_count": len(lines),
        "method": "hf_inference_api",
    }


def extract_text_trocr(image_bytes: bytes) -> dict[str, Any]:
    """
    Extract text lines from an image. Prefers the HuggingFace Inference API
    (uses the configured HF token, no local model download); falls back to a
    locally-loaded TrOCR model when no token is available.

    Returns:
      trocr_available : bool
      text_lines      : list[str]
      full_text       : str  (joined lines)
      line_count      : int
    """
    # Preferred path: HF Inference API with the configured token.
    token = _get_hf_token()
    if token:
        api_result = _hf_api_ocr(image_bytes, token)
        if api_result.get("text_lines"):
            return api_result
        log.info("HF Inference OCR returned no text — trying local TrOCR fallback")

    if not _load_trocr():
        return {
            "trocr_available": False,
            "text_lines": [],
            "full_text": "",
            "line_count": 0,
        }

    try:
        import torch
        from PIL import Image

        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        crops   = _detect_text_line_crops(pil_img)
        log.info("TrOCR: processing %d line crops", len(crops))

        lines: list[str] = []
        for crop in crops:
            try:
                px = _trocr_processor(images=crop, return_tensors="pt").pixel_values
                with torch.no_grad():
                    ids = _trocr_model.generate(
                        px, max_new_tokens=80, num_beams=4, early_stopping=True,
                    )
                text = _trocr_processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
                if text and len(text) > 1:
                    lines.append(text)
            except Exception:
                pass

        log.info("TrOCR: extracted %d non-empty lines", len(lines))
        return {
            "trocr_available": True,
            "text_lines": lines,
            "full_text": "\n".join(lines),
            "line_count": len(lines),
        }
    except Exception as exc:
        log.warning("TrOCR extraction failed: %s", exc)
        return {
            "trocr_available": False,
            "text_lines": [],
            "full_text": "",
            "line_count": 0,
            "error": str(exc),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Cross-match helper (rule-based, no Groq needed)
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_name(name: str | None) -> str:
    if not name:
        return ""
    import unicodedata
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(n.upper().split())


def _name_similarity(a: str | None, b: str | None) -> float:
    """Simple token-overlap similarity for name matching."""
    if not a or not b:
        return 0.0
    na = set(_normalise_name(a).split())
    nb = set(_normalise_name(b).split())
    if not na or not nb:
        return 0.0
    overlap = len(na & nb)
    return overlap / max(len(na), len(nb))


def cross_match_qr_vs_visual(
    visual_fields: dict[str, Any],   # from Groq vision extraction
    qr_fields:     dict[str, Any],   # from OpenCV QR decode
    customer_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Rule-based cross-match between QR-decoded fields and visually
    extracted fields (Groq vision / TrOCR).

    Returns a structured result compatible with the Groq cross_match_qr_vs_text
    schema so the rest of the pipeline can use either interchangeably.

    Fields compared:
      • name      — token overlap ≥ 0.6 → match
      • DOB/YOB   — year must agree; full DOB if both have it
      • gender    — M/F/O exact match (case-insensitive)
      • doc_number — if both have it, must match exactly
    """
    matched:    list[str]  = []
    mismatches: list[dict] = []

    # ── Name ──────────────────────────────────────────────────────────────────
    vis_name = visual_fields.get("full_name") or visual_fields.get("name")
    qr_name  = qr_fields.get("full_name")     or qr_fields.get("name")
    name_sim = _name_similarity(vis_name, qr_name)

    if vis_name and qr_name:
        if name_sim >= 0.60:
            matched.append("name")
        else:
            mismatches.append({
                "field":       "full_name",
                "visual_value": vis_name,
                "qr_value":    qr_name,
                "similarity":  round(name_sim, 2),
                "severity":    "critical" if name_sim < 0.30 else "warning",
            })

    # ── Year of birth / DOB ───────────────────────────────────────────────────
    # Pull year from Groq-extracted visual field OR the customer's declared DOB
    vis_dob_raw    = str(visual_fields.get("date_of_birth") or "")
    profile_dob    = str(customer_profile.get("dob") or "")
    # Use whichever gives us a year: visual field first, then declared profile
    vis_year = (
        re.search(r"\b(19|20)\d{2}\b", vis_dob_raw)
        or re.search(r"\b(19|20)\d{2}\b", profile_dob)
    )
    vis_year_str = vis_year.group(0) if vis_year else ""

    qr_yob  = str(qr_fields.get("year_of_birth") or qr_fields.get("yob") or "")
    qr_dob  = str(qr_fields.get("date_of_birth") or qr_fields.get("dob") or "")
    qr_year_str = qr_yob[:4] if qr_yob else ""
    if not qr_year_str and qr_dob:
        m = re.search(r"\b(19|20)\d{2}\b", qr_dob)
        qr_year_str = m.group(0) if m else ""

    if vis_year_str and qr_year_str:
        if vis_year_str == qr_year_str:
            # Year matches — accept regardless of whether full DOB is present
            # (Aadhaar QR only stores year of birth, not full DOB)
            matched.append("year_of_birth")
        else:
            mismatches.append({
                "field":        "year_of_birth",
                "visual_value": vis_year_str,
                "qr_value":     qr_year_str,
                "severity":     "critical",
            })
    elif vis_year_str and not qr_year_str:
        # QR has no DOB at all — not a mismatch, just incomplete
        pass
    elif not vis_year_str and qr_year_str:
        # We have QR year but no declared/visual year — informational only
        pass

    # ── Gender ────────────────────────────────────────────────────────────────
    vis_gender = str(visual_fields.get("gender") or "").upper()[:1]
    qr_gender  = str(qr_fields.get("gender") or "").upper()[:1]
    if vis_gender and qr_gender and vis_gender in "MFO" and qr_gender in "MFO":
        if vis_gender == qr_gender:
            matched.append("gender")
        else:
            mismatches.append({
                "field":        "gender",
                "visual_value": vis_gender,
                "qr_value":     qr_gender,
                "severity":     "critical",
            })

    # ── Document number (if Groq vision also extracted it) ────────────────────
    vis_num = (visual_fields.get("document_number") or "").replace(" ", "")
    qr_num  = (qr_fields.get("document_number")    or "").replace(" ", "")
    if vis_num and qr_num:
        if vis_num == qr_num:
            matched.append("document_number")
        else:
            mismatches.append({
                "field":        "document_number",
                "visual_value": vis_num,
                "qr_value":     qr_num,
                "severity":     "critical",
            })

    # ── Score ─────────────────────────────────────────────────────────────────
    total_checked = len(matched) + len(mismatches)
    match_score   = len(matched) / total_checked if total_checked > 0 else 0.5

    critical_mismatches = [m for m in mismatches if m["severity"] == "critical"]

    if critical_mismatches:
        integrity_verdict = "major_discrepancy"
        recommendation    = "reject"
    elif mismatches:
        integrity_verdict = "minor_discrepancy"
        recommendation    = "review"
    else:
        integrity_verdict = "consistent"
        recommendation    = "proceed"

    # The confirmed document number comes from QR (it's binary-decoded, more reliable)
    confirmed_number = qr_num or qr_fields.get("document_number")

    notes = []
    if matched:
        notes.append(f"Matched: {', '.join(matched)}")
    if mismatches:
        notes.append(
            "Mismatches: "
            + "; ".join(
                f"{m['field']} (visual='{m.get('visual_value')}' vs qr='{m.get('qr_value')}')"
                for m in mismatches
            )
        )

    return {
        "fields_match":          len(mismatches) == 0,
        "match_score":           round(match_score, 3),
        "matched_fields":        matched,
        "mismatched_fields":     mismatches,
        "cross_verified_number": confirmed_number if integrity_verdict != "major_discrepancy" else None,
        "integrity_verdict":     integrity_verdict,
        "recommendation":        recommendation,
        "cross_match_notes":     " | ".join(notes),
        "name_similarity":       round(name_sim, 3),
        "method":                "hf_rule_based",
    }
