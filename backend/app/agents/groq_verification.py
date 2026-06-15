from app.agents.base import log_event
from app.models.state import KYCState
from app.services.groq_client import verify_customer_details


def groq_verification_agent(state: KYCState) -> KYCState:
    profile = state.customer_profile
    result = verify_customer_details(profile)

    state.groq_verification = {
        "provider": "Groq",
        "model": "llama-3.3-70b-versatile",
        "result": result,
        "confidence": result.get("confidence", 0.0),
        "is_plausible": result.get("is_plausible", True),
        "risk_flags": result.get("risk_flags", []),
        "summary": result.get("summary", ""),
    }
    state.workflow_path.append("groq_verification")
    log_event(
        state,
        "Groq Verification Agent",
        f"AI profile verification complete (confidence: {result.get('confidence', 'N/A')})",
        {"risk_flags": result.get("risk_flags", []), "plausible": result.get("is_plausible")},
    )
    return state
