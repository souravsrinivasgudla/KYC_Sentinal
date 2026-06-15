"""
Evidence Validation Agent
==========================
Performs Groq LLM semantic cross-validation of uploaded documents.

IMPORTANT: Document type classification and structural validity
are handled UPSTREAM by indian_document_verification_agent (Stage 1b).
That agent uses Groq Vision + HuggingFace OpenCV QR + XGBoost models.

This agent's role:
  • Reuse the already-computed document_verdict from the Indian
    Document Verification Agent (do NOT re-classify images with
    the old text-based path — that produces wrong results for images)
  • Run Groq LLM semantic validation to cross-check document
    content against the declared customer profile
  • Produce a combined validation result for the evidence tab
"""

from __future__ import annotations

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.evidence_store import get_evidence
from app.services.groq_client import validate_uploaded_documents


def evidence_validation_agent(state: KYCState) -> KYCState:
    evidence_ids = state.customer_profile.get("evidence_ids", [])
    uploaded     = state.uploaded_evidence or get_evidence(evidence_ids)

    media_evidence  = state.adverse_media.get("evidence", [])
    validated_media = [e for e in media_evidence if e.get("severity") in ("High", "Medium")]

    # ── No documents uploaded ─────────────────────────────────────────────────
    if not uploaded:
        state.evidence_validation = {
            "validation_passed": False,
            "documents_reviewed": [],
            "identity_verified": False,
            "proof_of_identity": False,
            "proof_of_funds_verified": False,
            "overall_confidence": 0.0,
            "critical_issues": ["No identity documents uploaded"],
            "recommendation": "review",
            "summary": "No proof documents uploaded. Manual review required.",
            "adverse_media_validated": validated_media,
            "groq_powered": False,
            "ml_classification": {
                "ml_used": False,
                "doc_types_detected": [],
                "all_valid": False,
                "any_valid": False,
                "has_poi": False,
                "has_poa": False,
            },
        }
        state.workflow_path.append("evidence_validation")
        log_event(state, "Evidence Validation Agent",
                  "No uploaded documents — validation failed", {"uploaded_count": 0})
        return state

    # ── Reuse Indian Document Verification results ────────────────────────────
    # document_verdict was set by indian_document_verification_agent earlier in
    # the pipeline. It used Groq Vision + OpenCV QR + XGBoost — the correct path
    # for image documents. We MUST use those results, not re-classify with text.
    doc_verdict = state.document_verdict

    if doc_verdict and doc_verdict.get("per_document"):
        # Build ml_summary from the already-computed document_verdict
        per_doc   = doc_verdict["per_document"]
        doc_types = [d["doc_type"] for d in per_doc]

        valid_docs   = [d for d in per_doc if d.get("verdict") == "VERIFIED"]
        invalid_docs = [d for d in per_doc if d.get("verdict") == "REJECTED"]
        review_docs  = [d for d in per_doc if d.get("verdict") == "NEEDS_REVIEW"]

        # For the purpose of evidence_validation:
        # VERIFIED + NEEDS_REVIEW both count as "any_valid" (NEEDS_REVIEW = not hard-rejected)
        passing_docs = valid_docs + review_docs

        has_poi = any(d.get("kyc_purpose", {}).get("poi") for d in passing_docs)
        has_poa = any(d.get("kyc_purpose", {}).get("poa") for d in passing_docs)

        validity_issues = []
        for d in invalid_docs:
            for issue in d.get("validity_issues", [])[:2]:
                validity_issues.append(f"{d['filename']}: {issue}")

        avg_completeness = (
            sum(d.get("completeness_score", 0) for d in per_doc) / max(len(per_doc), 1)
        )
        avg_trust = (
            sum(d.get("trust_signal_score", 0) for d in per_doc) / max(len(per_doc), 1)
        )

        ml_summary = {
            "ml_used":           True,
            "doc_types_detected": doc_types,
            "doc_count":         len(per_doc),
            "valid_count":       len(valid_docs),
            "invalid_count":     len(invalid_docs),
            "all_valid":         len(invalid_docs) == 0,
            "any_valid":         len(passing_docs) > 0,
            "has_poi":           has_poi,
            "has_poa":           has_poa,
            "validity_issues":   validity_issues,
            "avg_completeness":  round(avg_completeness, 3),
            "avg_trust_signal":  round(avg_trust, 3),
            # Forward per-document details from the upstream agent
            "per_document": [
                {
                    "evidence_id":         d.get("evidence_id"),
                    "filename":            d.get("filename"),
                    "doc_type":            d.get("doc_type"),
                    "doc_type_display":    d.get("doc_type_display"),
                    "doc_type_confidence": d.get("doc_type_confidence", 0),
                    "is_valid":            d.get("verdict") == "VERIFIED",
                    "validity_confidence": d.get("validity_confidence", 0),
                    "validity_issues":     d.get("validity_issues", []),
                    "doc_number":          d.get("doc_number"),
                    "kyc_purpose":         d.get("kyc_purpose", {}),
                    "completeness_score":  d.get("completeness_score", 0),
                    "trust_signal_score":  d.get("trust_signal_score", 0),
                    "all_type_probabilities": d.get("all_type_probabilities", {}),
                    "groq_extracted_fields":  d.get("groq_extracted_fields", {}),
                    "groq_notes":          d.get("groq_notes", ""),
                    "groq_integrity_score": d.get("groq_integrity_score"),
                    "groq_profile_match":  d.get("groq_profile_match", {}),
                }
                for d in per_doc
            ],
            # Note the source so the UI knows these came from the upstream agent
            "_source": "indian_document_verification_agent",
        }
        ml_valid = ml_summary["any_valid"]
    else:
        # No upstream results (pipeline ran without the doc verification agent)
        # Fall back to a minimal summary based on what we know
        ml_summary = {
            "ml_used": False,
            "doc_types_detected": [],
            "doc_count": len(uploaded),
            "valid_count": 0,
            "invalid_count": len(uploaded),
            "all_valid": False,
            "any_valid": False,
            "has_poi": False,
            "has_poa": False,
            "validity_issues": [],
            "avg_completeness": 0.0,
            "avg_trust_signal": 0.0,
            "per_document": [],
            "_source": "fallback",
        }
        ml_valid = False

    # ── Groq LLM semantic validation ──────────────────────────────────────────
    # Pass text content for text-based docs; for images pass Groq-extracted
    # fields as a text summary so the semantic validator has real data
    doc_payload = []
    for d in uploaded:
        # For image docs, build a text summary from groq_extracted_fields
        # (already extracted by indian_document_verification_agent via Vision)
        groq_fields = {}
        if doc_verdict and doc_verdict.get("per_document"):
            for vdoc in doc_verdict["per_document"]:
                if vdoc.get("filename") == d.get("original_filename") or \
                   vdoc.get("evidence_id") == d.get("evidence_id"):
                    groq_fields = vdoc.get("groq_extracted_fields", {})
                    break

        if d.get("is_image") or d.get("needs_vision"):
            # Build a structured text summary from vision-extracted fields
            if groq_fields:
                text_summary = "Document fields extracted via Groq Vision:\n"
                for k, v in groq_fields.items():
                    text_summary += f"  {k}: {v}\n"
            else:
                text_summary = d.get("text_content", "")
            doc_payload.append({
                "filename":           d.get("original_filename", ""),
                "text_content":       text_summary,
                "extraction_method":  "vision_summary",
                "is_image":           False,  # treat as text for semantic validation
            })
        else:
            doc_payload.append({
                "filename":           d.get("original_filename", ""),
                "text_content":       d.get("text_content", ""),
                "extraction_method":  d.get("extraction_method", ""),
                "is_image":           False,
            })

    groq_result = validate_uploaded_documents(state.customer_profile, doc_payload)
    groq_valid  = groq_result.get("validation_passed", False)

    # Hard fail if declared ID does not match document
    id_mismatch = state.document_verdict.get("id_mismatch")
    if id_mismatch:
        groq_valid = False
        groq_result["id_number_matches_declared"] = False
        if id_mismatch["reason"] not in groq_result.get("critical_issues", []):
            groq_result.setdefault("critical_issues", []).insert(0, id_mismatch["reason"])

    name_mismatch = state.document_verdict.get("name_mismatch")
    if name_mismatch:
        groq_valid = False
        if name_mismatch["reason"] not in groq_result.get("critical_issues", []):
            groq_result.setdefault("critical_issues", []).insert(0, name_mismatch["reason"])

    # ── Combined result ───────────────────────────────────────────────────────
    # For the combined pass:
    #   - Indian doc verification VERIFIED/NEEDS_REVIEW + Groq semantic ok = PASS
    #   - If Indian doc verification was REJECTED, pipeline already short-circuited
    #     (this agent wouldn't run), so here ml_valid=True means at least NEEDS_REVIEW
    combined_passed = ml_valid and groq_valid

    all_critical_issues = list(groq_result.get("critical_issues", []))
    if ml_summary.get("validity_issues"):
        all_critical_issues.extend(ml_summary["validity_issues"][:3])

    state.evidence_validation = {
        **groq_result,
        "ml_classification":      ml_summary,
        "doc_types_detected":     ml_summary["doc_types_detected"],
        "has_proof_of_identity":  ml_summary["has_poi"],
        "has_proof_of_address":   ml_summary["has_poa"],
        "validation_passed":      combined_passed,
        "ml_validation_passed":   ml_valid,
        "groq_validation_passed": groq_valid,
        "critical_issues":        all_critical_issues,
        "adverse_media_validated": validated_media,
        "uploaded_documents": [
            {"evidence_id": d.get("evidence_id"), "filename": d.get("original_filename")}
            for d in uploaded
        ],
        "groq_powered": True,
    }
    state.adverse_media["validated_evidence"] = validated_media
    state.workflow_path.append("evidence_validation")

    doc_types_str = ", ".join(ml_summary.get("doc_types_detected", ["unknown"]))
    log_event(
        state,
        "Evidence Validation Agent",
        (
            f"Validation complete [{doc_types_str}] — "
            f"ML: {ml_valid} (from upstream), "
            f"Groq semantic: {groq_valid}, Combined: {combined_passed}"
        ),
        {
            "identity_verified":  groq_result.get("identity_verified"),
            "confidence":         groq_result.get("overall_confidence"),
            "has_poi":            ml_summary["has_poi"],
            "has_poa":            ml_summary["has_poa"],
            "ml_valid_count":     ml_summary.get("valid_count", 0),
            "source":             ml_summary.get("_source"),
        },
    )
    return state
