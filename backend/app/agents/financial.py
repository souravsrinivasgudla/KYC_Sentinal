from app.agents.base import log_event
from app.models.state import KYCState
from app.services.data_loader import load_country_risk, load_occupation_risk


def financial_profiling_agent(state: KYCState) -> KYCState:
    profile = state.customer_profile
    country_risk = load_country_risk()
    occupation_risk = load_occupation_risk()

    nationality = profile.get("nationality_normalized", profile.get("nationality", ""))
    occupation = profile.get("occupation_normalized", profile.get("occupation", ""))
    source_of_funds = profile.get("source_of_funds", "").strip()

    country_score = country_risk.get(nationality, 10)
    occupation_score = occupation_risk.get(occupation, 15)
    missing_funds = not bool(source_of_funds)
    missing_funds_score = 15 if missing_funds else 0

    factors = [
        {"factor": "Country Risk", "score": country_score, "detail": nationality},
        {"factor": "Occupation Risk", "score": occupation_score, "detail": occupation},
    ]
    if missing_funds:
        factors.append({"factor": "Missing Source of Funds", "score": missing_funds_score, "detail": "Not provided"})

    total = country_score + occupation_score + missing_funds_score

    state.financial_profile = {
        "country_risk_score": country_score,
        "occupation_risk_score": occupation_score,
        "missing_source_of_funds": missing_funds,
        "missing_funds_score": missing_funds_score,
        "factors": factors,
        "financial_risk_score": total,
    }
    state.workflow_path.append("financial_profiling")
    log_event(
        state,
        "Financial Profiling Agent",
        f"Financial risk factors assessed (score: {total})",
        {"factors": factors},
    )
    return state
