import re

from app.agents.base import log_event
from app.models.state import KYCState

REQUIRED_FIELDS = ["name", "dob", "nationality", "occupation"]
OPTIONAL_FIELDS = ["source_of_funds", "document_type", "id_number"]
FIELD_LABELS = {
    "name": "Full Name",
    "dob": "Date of Birth",
    "nationality": "Nationality",
    "occupation": "Occupation",
    "source_of_funds": "Source of Funds",
<<<<<<< HEAD
    "id_number": "ID / DL Number",
=======
    "document_type": "Document Type",
    "id_number": "Document Number",
>>>>>>> 16747735b61a04e93825a71ffd62d65d9cf78d0d
}


def _field_confidence(value: str, pattern: str | None = None) -> float:
    if not value or not value.strip():
        return 0.0
    conf = 0.85
    if len(value.strip()) >= 2:
        conf += 0.05
    if pattern and re.match(pattern, value.strip()):
        conf += 0.05
    return min(conf, 0.99)


def document_extraction_agent(state: KYCState) -> KYCState:
    profile = state.customer_profile
    fields = {
        "name": profile.get("name", ""),
        "dob": profile.get("dob", ""),
        "nationality": profile.get("nationality", ""),
        "occupation": profile.get("occupation", ""),
        "source_of_funds": profile.get("source_of_funds", ""),
        "document_type": profile.get("document_type", ""),
        "id_number": profile.get("id_number", ""),
    }

    confidences = {
        "name": _field_confidence(fields["name"]),
        "dob": _field_confidence(fields["dob"], r"^\d{4}-\d{2}-\d{2}$"),
        "nationality": _field_confidence(fields["nationality"]),
        "occupation": _field_confidence(fields["occupation"]),
        "source_of_funds": _field_confidence(fields["source_of_funds"]) if fields["source_of_funds"] else 0.0,
        "document_type": _field_confidence(fields["document_type"]) if fields["document_type"] else 0.0,
        "id_number": _field_confidence(fields["id_number"]) if fields["id_number"] else 0.0,
    }

    missing_required = [f for f in REQUIRED_FIELDS if not fields[f] or not str(fields[f]).strip()]
    missing_optional = [f for f in OPTIONAL_FIELDS if not fields[f] or not str(fields[f]).strip()]
    missing_all = missing_required + missing_optional
    provided = [k for k, v in fields.items() if v and str(v).strip()]
    overall = round(sum(confidences.values()) / len(confidences), 2)

    field_status = {
        k: {
            "value": fields[k],
            "provided": bool(fields[k] and str(fields[k]).strip()),
            "required": k in REQUIRED_FIELDS,
            "confidence": confidences[k],
            "label": FIELD_LABELS[k],
            "status": "missing" if k in missing_all else ("low_confidence" if confidences[k] < 0.7 else "ok"),
        }
        for k in fields
    }

    extraction = {
        "extracted_fields": fields,
        "field_confidence": confidences,
        "field_status": field_status,
        "overall_confidence": overall,
        "fields_provided": provided,
        "fields_missing": missing_all,
        "fields_missing_required": missing_required,
        "fields_missing_optional": missing_optional,
        "validation_passed": len(missing_required) == 0 and overall >= 0.6,
        "has_missing_optional": len(missing_optional) > 0,
    }

    state.document_extraction = extraction
    state.workflow_path.append("document_extraction")
    log_event(
        state,
        "Document Extraction Agent",
        f"Extracted {len(provided)} fields (confidence: {overall})",
        {
            "confidences": confidences,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
        },
    )
    return state
