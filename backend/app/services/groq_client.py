import json
import re
from typing import Any

import httpx

from app.config import settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_response": text, "parse_error": True}


def groq_chat(system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
    if not settings.groq_api_key:
        return {"error": "GROQ_API_KEY not configured", "fallback": True}

    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_response(content)


# Vision model used for image analysis (Groq Llama 4 Scout supports vision)
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def groq_vision_chat(
    system: str,
    text_prompt: str,
    image_base64: str,
    media_type: str = "image/jpeg",
    temperature: float = 0.05,
) -> dict[str, Any]:
    """
    Send an image to Groq's vision model along with a text prompt.
    Returns parsed JSON response.

    Uses meta-llama/llama-4-scout-17b-16e-instruct which supports
    vision (image_url with base64 data URLs).
    """
    if not settings.groq_api_key:
        return {"error": "GROQ_API_KEY not configured", "fallback": True}

    data_url = f"data:{media_type};base64,{image_base64}"

    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                    {
                        "type": "text",
                        "text": text_prompt,
                    },
                ],
            },
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    with httpx.Client(timeout=90.0) as client:
        resp = client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_response(content)


def extract_fields_from_image(
    image_base64: str,
    media_type: str,
    filename: str,
    customer_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Use Groq Vision (Llama 4 Scout) to extract all structured fields
    directly from an image of an Indian KYC document.

    Called for:
      - .jpg / .jpeg / .png / .webp uploads
      - Scanned / image-based PDFs (no selectable text)

    Returns the same schema as extract_fields_from_document so it can
    be used as a drop-in replacement when text extraction yields nothing.
    """
    system = (
        "You are an expert Indian KYC document analyst with vision capabilities. "
        "You can read Indian government-issued identity documents from images. "
        "Supported document types: Aadhaar Card (UIDAI), PAN Card (Income Tax Dept), "
        "Indian Passport (MEA), Voter ID / EPIC (Election Commission), "
        "Driving Licence (RTO). "
        "Extract ALL visible text and structured fields from the image. "
        "Respond ONLY with valid JSON."
    )

    customer_name = customer_profile.get("name", "")
    customer_dob  = customer_profile.get("dob", "")
    customer_id   = customer_profile.get("id_number", "")
    customer_doc  = customer_profile.get("document_type", "")

    prompt = f"""Customer declared name: {customer_name}
Customer declared DOB: {customer_dob}
Customer declared document type: {customer_doc}
Customer declared ID / account number (must match document): {customer_id}
Filename: {filename}

IMPORTANT — Driving Licence:
  document_number MUST be the exact value beside "DL No", "DL No.", "Licence No",
  or "License No" on the licence (e.g. AP43720240003089, TN01 20190012345).
  full_name MUST be the licence holder name as printed on the document.
  Set name_matches true only when the declared customer name matches that holder name.
  NEVER use a date or "Valid Till" / "Date of Issue" value as document_number.

IMPORTANT DOB MATCHING RULE:
  Many Indian documents (especially Aadhaar) only print the year of birth,
  not the full date. If the document shows only a year (e.g. "2002") and the
  customer's declared DOB contains the same year (e.g. "2002-01-01"),
  treat dob_matches as TRUE — this is not a mismatch.
  Only flag dob_matches as FALSE if the year itself is different.

Look at this Indian KYC document image carefully.
Read ALL text visible on the document — front and back.
Extract every field you can see.

Return JSON with this exact structure:
{{
  "documents": [
    {{
      "filename": "{filename}",
      "detected_doc_type": "aadhaar_card|pan_card|passport|voter_id|driving_licence|unknown",
      "extracted_fields": {{
        "full_name": "name as printed on document or null",
        "date_of_birth": "DD/MM/YYYY or null",
        "gender": "M/F/Other or null",
        "document_number": "primary ID on document — for driving_licence use DL No/Licence No only (e.g. AP43720240003089) or null",
        "expiry_date": "DD/MM/YYYY or null",
        "address": "full address string or null",
        "father_name": "father/spouse name or null",
        "issuing_authority": "UIDAI/Income Tax Dept/MEA/ECI/RTO/Bank or null",
        "issue_date": "DD/MM/YYYY or null",
        "nationality": "Indian or null",
        "photo_present": true/false,
        "signature_present": true/false,
        "qr_or_barcode_present": true/false,
        "language_secondary": true/false,
        "ifsc_code": "IFSC code or null",
        "mrz_present": true/false
      }},
      "profile_match": {{
        "name_matches": true/false/null,
        "dob_matches": true/false/null,
        "id_number_matches": true/false/null,
        "name_similarity": 0.0-1.0,
        "mismatch_details": []
      }},
      "document_integrity": {{
        "appears_genuine": true/false,
        "integrity_score": 0.0-1.0,
        "integrity_issues": []
      }},
      "groq_notes": "what you can and cannot read from this image"
    }}
  ],
  "overall_assessment": "brief summary"
}}"""

    try:
        result = groq_vision_chat(system, prompt, image_base64, media_type, temperature=0.05)
        result["_source"] = "vision"
        return result
    except Exception as exc:
        return {
            "parse_error": True,
            "error": str(exc),
            "_source": "vision_failed",
            "documents": [],
        }
def generate_escalation_reasons(
    decision: str,
    risk_score: int,
    risk_level: str,
    breakdown: list[dict[str, Any]],
    customer_profile: dict[str, Any],
    document_verdict: dict[str, Any] | None = None,
    id_mismatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Use Groq to generate clear, plain-English one-liner reasons
    explaining WHY a KYC case was ESCALATED or flagged for REVIEW.

    Each reason is a single concise sentence a compliance officer
    can read and act on immediately — no jargon, no point scores.

    Returns:
      reasons:       list[str]  — one-liner sentences (3-6 items)
      summary:       str        — single paragraph executive summary
      urgency:       str        — "immediate" | "standard" | "low"
      groq_powered:  bool
    """
    if not settings.groq_api_key:
        # Fallback: convert breakdown to plain sentences
        fallback_reasons = [
            _breakdown_to_sentence(b) for b in breakdown if b.get("points", 0) >= 10
        ]
        if id_mismatch:
            fallback_reasons.insert(0, id_mismatch.get("reason", "ID number mismatch detected"))
        return {
            "reasons":      fallback_reasons or ["Risk score exceeds threshold"],
            "summary":      f"KYC {decision}: risk score {risk_score}/100 ({risk_level})",
            "urgency":      "immediate" if risk_score >= 70 else "standard",
            "groq_powered": False,
        }

    # Build context for Groq
    signals = []
    for b in breakdown:
        pts = b.get("points", 0)
        if pts >= 5:
            signals.append(f"- {b['signal']} (weight: {pts})")

    doc_context = ""
    if document_verdict:
        verdict = document_verdict.get("verdict", "")
        if verdict == "REJECTED":
            reasons = document_verdict.get("rejection_reasons", [])
            doc_context = f"\nDocument Verification: REJECTED\n" + "\n".join(f"  - {r}" for r in reasons[:3])
        elif verdict == "NEEDS_REVIEW":
            doc_context = f"\nDocument Verification: Flagged for review ({document_verdict.get('summary','')})"

    id_context = ""
    if id_mismatch:
        id_context = (
            f"\nID Number Mismatch: Customer declared '{id_mismatch.get('declared')}' "
            f"but document shows '{id_mismatch.get('extracted')}'"
        )

    system = (
        "You are a senior KYC compliance analyst writing escalation notices. "
        "Convert technical risk signals into clear, plain-English one-liner sentences "
        "that a compliance officer can immediately understand and act on. "
        "Each sentence must be under 15 words. Be specific — name the actual risk. "
        "Do NOT use technical jargon, point scores, or ML terminology. "
        "Respond ONLY with valid JSON."
    )

    user = f"""KYC Decision: {decision}
Risk Score: {risk_score}/100 ({risk_level})
Customer: {customer_profile.get("name", "")} | {customer_profile.get("nationality", "")} | {customer_profile.get("occupation", "")}

Risk signals triggered:
{chr(10).join(signals) if signals else "- Risk score threshold exceeded"}{doc_context}{id_context}

Write 3-6 plain-English one-liner reasons explaining why this case requires {decision.lower()}.
Each reason should tell a compliance officer specifically what to investigate.

Return JSON:
{{
  "reasons": [
    "One clear sentence explaining the specific risk",
    "Another specific concern for the compliance officer",
    "..."
  ],
  "summary": "Single paragraph executive summary (2-3 sentences) for the compliance officer",
  "urgency": "immediate|standard|low"
}}"""

    try:
        result = groq_chat(system, user, temperature=0.2)
        if result.get("parse_error") or result.get("fallback"):
            raise ValueError("Groq parse error")
        return {
            "reasons":      result.get("reasons", []),
            "summary":      result.get("summary", ""),
            "urgency":      result.get("urgency", "standard"),
            "groq_powered": True,
        }
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("escalation_reasons Groq call failed: %s", exc)
        fallback = [_breakdown_to_sentence(b) for b in breakdown if b.get("points", 0) >= 10]
        if id_mismatch:
            fallback.insert(0, id_mismatch.get("reason", "ID number mismatch detected"))
        return {
            "reasons":      fallback or [f"Risk score {risk_score}/100 exceeds {decision.lower()} threshold"],
            "summary":      f"KYC {decision}: {risk_level} risk profile (score {risk_score}/100).",
            "urgency":      "immediate" if risk_score >= 70 else "standard",
            "groq_powered": False,
        }


def _breakdown_to_sentence(b: dict[str, Any]) -> str:
    """Convert a risk breakdown item to a plain English sentence."""
    signal = b.get("signal", "")
    s = signal.lower()
    if "sanctions" in s:
        return "Customer name matches an entry on the sanctions watchlist."
    if "pep" in s:
        return "Customer is identified as a Politically Exposed Person (PEP)."
    if "adverse media" in s:
        return "Adverse media coverage found linked to this customer."
    if "source of funds" in s:
        return "Customer has not provided a source of funds."
    if "occupation" in s:
        return "Customer's occupation is classified as high-risk."
    if "country" in s:
        return "Customer's country of origin carries elevated risk."
    if "id number" in s or "mismatch" in s:
        return "Entered ID number does not match the number on the uploaded document."
    if "document" in s:
        return "Uploaded identity document failed verification checks."
    if "groq" in s:
        return "AI profile analysis flagged anomalies in customer data."
    return f"{signal} triggered during KYC assessment."


def verify_customer_details(profile: dict[str, Any]) -> dict[str, Any]:
    system = (
        "You are a KYC compliance analyst. Validate customer onboarding data for consistency, "
        "plausibility, and completeness. Respond ONLY with valid JSON."
    )
    user = f"""Analyze this customer profile for KYC onboarding:

{json.dumps(profile, indent=2)}

Return JSON:
{{
  "is_plausible": true/false,
  "confidence": 0.0-1.0,
  "field_checks": [{{"field": "name", "valid": true, "note": "..."}}],
  "risk_flags": ["list of concerns"],
  "missing_critical": ["fields that should be collected"],
  "summary": "brief assessment"
}}"""
    return groq_chat(system, user)


def extract_fields_from_document(
    profile: dict[str, Any],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Use Groq LLM to extract structured fields from each uploaded
    Indian KYC document. Returns per-document field extractions.
    """
    system = (
        "You are an expert Indian KYC document analyst. "
        "Your task is to extract all structured fields from Indian government-issued "
        "identity and address proof documents. "
        "Supported document types: Aadhaar Card, PAN Card, Passport, Voter ID (EPIC), "
        "Driving Licence. "
        "Respond ONLY with valid JSON. Be precise — only report fields that are "
        "explicitly present in the document text."
    )

    customer_name = profile.get("name", "")
    customer_dob  = profile.get("dob", "")
    customer_nat  = profile.get("nationality", "")
    customer_id   = profile.get("id_number", "")

    doc_block = json.dumps(
        [
            {
                "filename": d.get("filename", d.get("original_filename", "")),
                "text_content": (d.get("text_content", "") or "")[:4000],
                "is_image": d.get("is_image", False),
                "extraction_method": d.get("extraction_method", ""),
            }
            for d in documents
        ],
        indent=2,
    )

    user = f"""Customer declared profile:
  name: {customer_name}
  dob: {customer_dob}
  nationality: {customer_nat}
  id_number / DL No: {customer_id}

For driving licences, document_number MUST be the value beside "DL No" or "Licence No"
(e.g. AP43720240003089). NEVER use a date like "OF 29-11-2024" as document_number.

Uploaded documents (extracted text):
{doc_block}

For EACH document, extract all available fields and verify them.
Return JSON:
{{
  "documents": [
    {{
      "filename": "...",
      "detected_doc_type": "aadhaar_card|pan_card|passport|voter_id|driving_licence|unknown",
      "extracted_fields": {{
        "full_name": "name as printed on document or null",
        "date_of_birth": "DD/MM/YYYY or null",
        "gender": "M/F/Other or null",
        "document_number": "primary ID — for driving_licence the DL No/Licence No on document or null",
        "expiry_date": "DD/MM/YYYY or null (null if no expiry)",
        "address": "full address string or null",
        "father_name": "father/guardian name or null",
        "issuing_authority": "UIDAI/Income Tax Dept/MEA/ECI/RTO/Bank name or null",
        "issue_date": "DD/MM/YYYY or null",
        "nationality": "Indian/null",
        "photo_present": true/false,
        "signature_present": true/false,
        "qr_or_barcode_present": true/false,
        "language_secondary": true/false,
        "ifsc_code": "IFSC code or null",
        "mrz_present": true/false
      }},
      "profile_match": {{
        "name_matches": true/false/null,
        "dob_matches": true/false/null,
        "name_similarity": 0.0-1.0,
        "mismatch_details": ["list any mismatches"]
      }},
      "document_integrity": {{
        "appears_genuine": true/false,
        "integrity_score": 0.0-1.0,
        "integrity_issues": ["tampered", "low quality", "expired", "incomplete", etc.]
      }},
      "groq_notes": "brief notes about this document"
    }}
  ],
  "overall_assessment": "brief summary of all documents"
}}"""

    return groq_chat(system, user, temperature=0.05)


def scan_qr_from_document(
    document_text: str,
    filename: str,
    doc_type: str,
    customer_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage 2a — QR/Barcode fallback scan.

    Called when Groq's first-pass extraction could NOT find a document
    number but DID detect a QR code or barcode is present in the document.

    Groq re-reads the document text to:
      1. Locate and decode any QR / barcode payload visible in the text
         (PDF text extractors often include encoded strings or XML/JSON
          payloads from embedded QR data)
      2. Extract all fields from the QR payload
      3. Return the QR-sourced document number and fields

    Returns a dict with:
      qr_found          : bool
      qr_document_number: str | None
      qr_fields         : dict  (all fields extracted from QR)
      qr_raw_payload    : str | None (raw QR string if found)
      scan_confidence   : float
      scan_notes        : str
    """
    system = (
        "You are a specialist in Indian government document QR codes and barcodes. "
        "Indian Aadhaar cards embed a QR code containing an XML/JSON payload with the "
        "holder's UID, name, DOB, gender, and address. "
        "PAN cards may contain a QR code with PAN number and holder details. "
        "Voter IDs (EPIC), Driving Licences, and Passports also contain machine-readable "
        "zones or barcodes with document number and holder data. "
        "Your job: find any QR/barcode payload in the provided document text and extract "
        "all fields from it. The payload may appear as encoded text, XML tags, JSON, "
        "or a long alphanumeric string. "
        "Respond ONLY with valid JSON."
    )

    doc_type_display = doc_type.replace("_", " ").title()
    user = f"""Document type: {doc_type_display}
Filename: {filename}
Customer declared name: {customer_profile.get("name", "")}
Customer declared DOB: {customer_profile.get("dob", "")}

Document text content (full):
{document_text[:5000]}

Search this text carefully for ANY QR code payload, barcode data, encoded string,
XML content, or machine-readable zone (MRZ) data. Common indicators:
  - Long alphanumeric strings (32+ chars)
  - XML-like tags: <uid>, <name>, <dob>, <gender>, <address>
  - JSON objects embedded in text
  - MRZ lines (2–3 lines of uppercase letters and digits/chevrons)
  - Base64-like encoded strings
  - Aadhaar QR XML format: XML with uid, name, dob, gender, co, loc, vtc, dist, state, pc, phone

Extract the document number and all other fields from the QR/barcode payload.

Return JSON:
{{
  "qr_found": true/false,
  "qr_type": "aadhaar_qr|pan_qr|mrz|barcode|unknown|none",
  "qr_document_number": "the ID number found in QR payload, or null",
  "qr_fields": {{
    "full_name": "name from QR or null",
    "date_of_birth": "DD/MM/YYYY from QR or null",
    "gender": "M/F/Other from QR or null",
    "address": "address from QR or null",
    "mobile_hash": "last 4 digits or hash of mobile if present or null",
    "email_hash": "hash of email if present or null",
    "uid_token": "VID or UID token if present or null",
    "expiry_date": "expiry from QR or null",
    "issuer": "issuing authority from QR or null"
  }},
  "qr_raw_payload": "first 200 chars of raw QR string if found, else null",
  "scan_confidence": 0.0-1.0,
  "scan_notes": "brief explanation of what was found or not found"
}}"""

    return groq_chat(system, user, temperature=0.0)


def cross_match_qr_vs_text(
    text_fields: dict[str, Any],
    qr_fields: dict[str, Any],
    doc_type: str,
    customer_profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage 2b — Cross-match QR-extracted fields against text-extracted fields.

    Compares what Groq found by reading the document text directly against
    what was found in the QR/barcode payload. Mismatches between the two
    sources indicate potential tampering or document alteration.

    Returns:
      fields_match      : bool   — do the key fields agree?
      match_score       : float  — 0.0-1.0 overall agreement
      matched_fields    : list   — fields that agree
      mismatched_fields : list   — fields that disagree (with details)
      cross_verified_number: str — confirmed document number (from QR)
      integrity_verdict : str    — "consistent"|"minor_discrepancy"|"major_discrepancy"
      recommendation    : str    — "proceed"|"review"|"reject"
      cross_match_notes : str
    """
    system = (
        "You are a forensic KYC document analyst performing cross-verification. "
        "You compare two independent sources of information extracted from the same document: "
        "one from reading the printed text, one from decoding the embedded QR/barcode. "
        "Any discrepancy between the two sources is a red flag for document tampering. "
        "Respond ONLY with valid JSON."
    )

    user = f"""Document type: {doc_type.replace("_", " ").title()}
Customer declared name: {customer_profile.get("name", "")}
Customer declared DOB: {customer_profile.get("dob", "")}

SOURCE A — Fields extracted from printed document text:
{json.dumps(text_fields, indent=2)}

SOURCE B — Fields extracted from QR/barcode payload:
{json.dumps(qr_fields, indent=2)}

Compare both sources field-by-field. Focus on:
  1. Name (must match within normal spelling variations)
  2. Date of birth (must match exactly)
  3. Document number (if present in both, must match exactly)
  4. Gender (must match if present in both)
  5. Address (may differ in formatting; flag only major differences)

Return JSON:
{{
  "fields_match": true/false,
  "match_score": 0.0-1.0,
  "matched_fields": ["name", "dob", ...],
  "mismatched_fields": [
    {{
      "field": "field_name",
      "text_value": "value from text",
      "qr_value": "value from QR",
      "severity": "critical|warning|minor"
    }}
  ],
  "cross_verified_number": "document number confirmed by cross-match, or null",
  "integrity_verdict": "consistent|minor_discrepancy|major_discrepancy",
  "recommendation": "proceed|review|reject",
  "cross_match_notes": "brief explanation"
}}"""

    return groq_chat(system, user, temperature=0.0)


def validate_uploaded_documents(
    profile: dict[str, Any],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    system = (
        "You are a KYC document verification specialist. Cross-check uploaded identity/financial "
        "proof documents against the declared customer profile. Respond ONLY with valid JSON."
    )
    doc_block = json.dumps(documents, indent=2)
    user = f"""Customer Profile:
{json.dumps(profile, indent=2)}

Uploaded Documents (extracted content):
{doc_block}

IMPORTANT: Compare profile id_number field against document_number in each document.
If they differ (e.g. wrong Aadhaar entered but correct document uploaded), set validation_passed=false
and add a critical_issue describing the mismatch.

Return JSON:
{{
  "documents_reviewed": [{{"filename": "...", "doc_type": "passport|id|proof_of_funds|other", "authenticity_score": 0.0-1.0, "matches_profile": true/false, "id_number_matches": true/false, "issues": []}}],
  "identity_verified": true/false,
  "id_number_matches_declared": true/false,
  "proof_of_identity": true/false,
  "proof_of_funds_verified": true/false,
  "overall_confidence": 0.0-1.0,
  "validation_passed": true/false,
  "critical_issues": [],
  "recommendation": "approve|review|reject",
  "summary": "explanation for compliance officer"
}}"""
    return groq_chat(system, user)


def human_review_assist(
    profile: dict[str, Any],
    evidence_validation: dict[str, Any],
    risk_assessment: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    system = (
        "You assist compliance officers with KYC human review. Provide structured guidance. "
        "Respond ONLY with valid JSON."
    )
    user = f"""Profile: {json.dumps(profile)}
Evidence Validation: {json.dumps(evidence_validation)}
Risk: {json.dumps(risk_assessment)}
System Decision: {json.dumps(decision)}

Return JSON:
{{
  "review_priority": "low|medium|high",
  "key_concerns": [],
  "evidence_gaps": [],
  "suggested_action": "approve|review|escalate",
  "officer_checklist": ["items for human reviewer"],
  "summary": "brief briefing for officer"
}}"""
    return groq_chat(system, user)
