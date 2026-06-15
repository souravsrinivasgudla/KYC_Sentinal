from datetime import datetime

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.country_mapper import normalize_country


def normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def normalize_date(dob: str) -> str:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(dob, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return dob


def normalization_agent(state: KYCState) -> KYCState:
    profile = state.customer_profile
    normalized = {
        **profile,
        "name_normalized": normalize_name(profile.get("name", "")),
        "dob_normalized": normalize_date(profile.get("dob", "")),
        "nationality_normalized": normalize_country(profile.get("nationality", "")),
        "occupation_normalized": profile.get("occupation", "").strip().title(),
    }
    state.customer_profile = normalized
    state.workflow_path.append("normalization")
    log_event(
        state,
        "Profile Normalization Agent",
        "Standardized customer data",
        {"normalized_fields": ["name", "dob", "nationality", "occupation"]},
    )
    return state
