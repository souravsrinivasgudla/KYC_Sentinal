from app.agents.base import log_event
from app.models.state import KYCState
from app.services.data_loader import load_adverse_media
from app.services.vector_store import vector_store


def adverse_media_agent(state: KYCState) -> KYCState:
    profile = state.customer_profile
    name = profile.get("name", "")
    query = f"{name} adverse media fraud corruption money laundering"

    vector_hits = vector_store.search(query, n_results=5, entity_type="adverse_media")
    all_media = load_adverse_media()

    name_lower = name.lower()
    direct_matches = [
        m
        for m in all_media
        if m["subject"].lower() == name_lower
        or any(a.lower() in name_lower or name_lower in a.lower() for a in m.get("aliases", []))
    ]

    evidence: list[dict] = []
    seen_ids: set[str] = set()

    for article in direct_matches:
        if article["id"] not in seen_ids and article.get("severity") != "Low":
            seen_ids.add(article["id"])
            evidence.append(
                {
                    "id": article["id"],
                    "title": article["title"],
                    "source": article["source"],
                    "date": article["date"],
                    "severity": article["severity"],
                    "categories": article.get("categories", []),
                    "summary": article.get("summary", ""),
                    "match_type": "exact",
                }
            )

    for hit in vector_hits:
        if hit["id"] in seen_ids:
            continue
        payload = hit["payload"]
        if payload.get("severity") == "Low":
            continue
        if hit["similarity"] >= 0.65:
            seen_ids.add(hit["id"])
            evidence.append(
                {
                    "id": hit["id"],
                    "title": payload.get("title", ""),
                    "source": payload.get("source", ""),
                    "date": payload.get("date", ""),
                    "severity": payload.get("severity", "Medium"),
                    "categories": payload.get("categories", []),
                    "summary": payload.get("summary", ""),
                    "match_type": "semantic",
                    "similarity": hit["similarity"],
                }
            )

    severities = [e["severity"] for e in evidence]
    if "High" in severities:
        overall_severity = "High"
    elif "Medium" in severities:
        overall_severity = "Medium"
    elif evidence:
        overall_severity = "Low"
    else:
        overall_severity = "None"

    state.adverse_media = {
        "match": len(evidence) > 0,
        "severity": overall_severity,
        "evidence": evidence,
        "article_count": len(evidence),
    }
    state.workflow_path.append("adverse_media")
    log_event(
        state,
        "Adverse Media Agent",
        f"Found {len(evidence)} adverse media articles",
        {"severity": overall_severity, "count": len(evidence)},
    )
    return state
