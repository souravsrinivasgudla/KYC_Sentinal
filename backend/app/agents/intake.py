from app.agents.base import log_event
from app.models.state import CustomerInput, KYCState


def intake_agent(state: KYCState, customer: CustomerInput) -> KYCState:
    profile = {
        "name": customer.name.strip(),
        "dob": customer.dob.strip(),
        "nationality": customer.nationality.strip(),
        "occupation": customer.occupation.strip(),
        "source_of_funds": customer.source_of_funds.strip(),
        "id_number": customer.id_number.strip(),
        "evidence_ids": customer.evidence_ids,
        "intake_confidence": 0.95 if customer.name and customer.dob else 0.7,
    }
    state.customer_profile = profile
    if customer.evidence_ids:
        from app.services.evidence_store import get_evidence

        state.uploaded_evidence = get_evidence(customer.evidence_ids)
    state.workflow_path.append("intake")
    log_event(state, "Customer Intake Agent", "Structured customer profile created", {"profile": profile})
    return state
