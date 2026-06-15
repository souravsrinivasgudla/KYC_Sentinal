from app.agents.base import log_event
from app.models.state import KYCState
from app.services.vector_store import vector_store


def compliance_screening_agent(state: KYCState) -> KYCState:
    profile = state.customer_profile
    query = (
        f"{profile.get('name', '')} {profile.get('dob', '')} "
        f"{profile.get('nationality', '')} {profile.get('occupation', '')}"
    )

    entity_matches = state.entity_resolution.get("matches", [])
    sanctions_hits = [m for m in entity_matches if m["type"] == "sanctions"]
    pep_hits = [m for m in entity_matches if m["type"] == "pep"]

    vector_sanctions = vector_store.search(query, n_results=3, entity_type="sanctions")
    vector_pep = vector_store.search(query, n_results=3, entity_type="pep")

    for hit in vector_sanctions:
        if hit["similarity"] >= 0.7 and hit["id"] not in {h["watchlist_id"] for h in sanctions_hits}:
            payload = hit["payload"]
            sanctions_hits.append(
                {
                    "watchlist_id": hit["id"],
                    "matched_name": payload.get("name", ""),
                    "type": "sanctions",
                    "name_similarity": int(hit["similarity"] * 100),
                    "composite_score": int(hit["similarity"] * 100),
                    "list": payload.get("list", ""),
                    "reason": payload.get("reason", ""),
                    "source": "vector_db",
                }
            )

    for hit in vector_pep:
        if hit["similarity"] >= 0.7 and hit["id"] not in {h["watchlist_id"] for h in pep_hits}:
            payload = hit["payload"]
            pep_hits.append(
                {
                    "watchlist_id": hit["id"],
                    "matched_name": payload.get("name", ""),
                    "type": "pep",
                    "name_similarity": int(hit["similarity"] * 100),
                    "composite_score": int(hit["similarity"] * 100),
                    "list": payload.get("list", ""),
                    "reason": payload.get("reason", ""),
                    "source": "vector_db",
                }
            )

    sanctions_match = len(sanctions_hits) > 0
    pep_match = len(pep_hits) > 0
    confidence = 0.94 if sanctions_match or pep_match else 0.88

    state.screening_results = {
        "sanctions": sanctions_match,
        "sanctions_hits": sanctions_hits,
        "pep": pep_match,
        "pep_hits": pep_hits,
        "watchlist_screened": True,
        "confidence": confidence,
    }
    state.workflow_path.append("compliance_screening")
    log_event(
        state,
        "Compliance Screening Agent",
        f"Sanctions: {sanctions_match}, PEP: {pep_match}",
        {"sanctions_hits": len(sanctions_hits), "pep_hits": len(pep_hits)},
    )
    return state
