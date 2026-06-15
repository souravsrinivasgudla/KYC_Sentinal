from rapidfuzz import fuzz

from app.agents.base import log_event
from app.models.state import KYCState
from app.services.data_loader import load_watchlist


def entity_resolution_agent(state: KYCState, deep: bool = False) -> KYCState:
    profile = state.customer_profile
    customer_name = profile.get("name_normalized", profile.get("name", "")).lower()
    customer_dob = profile.get("dob_normalized", profile.get("dob", ""))
    customer_nat = profile.get("nationality_normalized", profile.get("nationality", "")).lower()

    watchlist = load_watchlist()
    matches: list[dict] = []

    for entry in watchlist:
        names = [entry["name"].lower()] + [a.lower() for a in entry.get("aliases", [])]
        name_scores = [fuzz.token_sort_ratio(customer_name, n) for n in names]
        best_name_score = max(name_scores) if name_scores else 0

        dob_match = entry.get("dob", "") == customer_dob
        nat_match = entry.get("nationality", "").lower() == customer_nat

        composite = best_name_score
        if dob_match:
            composite += 15
        if nat_match:
            composite += 10
        composite = min(composite, 100)

        threshold = 75 if deep else 65
        if composite >= threshold:
            matches.append(
                {
                    "watchlist_id": entry["id"],
                    "matched_name": entry["name"],
                    "type": entry["type"],
                    "name_similarity": best_name_score,
                    "dob_match": dob_match,
                    "nationality_match": nat_match,
                    "composite_score": composite,
                    "list": entry.get("list", ""),
                    "reason": entry.get("reason", ""),
                }
            )

    matches.sort(key=lambda m: m["composite_score"], reverse=True)
    resolved = len(matches) == 0 or all(m["composite_score"] < 85 for m in matches)

    state.entity_resolution = {
        "matches": matches,
        "is_unique_entity": resolved,
        "match_count": len(matches),
        "deep_resolution": deep,
        "confidence": 0.92 if resolved else 0.78,
    }
    state.workflow_path.append("entity_resolution" + ("_deep" if deep else ""))
    log_event(
        state,
        "Entity Resolution Agent",
        f"Found {len(matches)} potential entity matches",
        {"matches": matches[:3], "deep": deep},
    )
    return state
