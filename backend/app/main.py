import json
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents.registry import AGENT_REGISTRY, build_agent_status
from app.config import settings
from app.models.state import CustomerInput, HumanReviewInput, KYCState
from app.orchestrator.graph import orchestrator
from app.services.case_store import (
    get_case,
    init_db,
    link_intake_case,
    list_cases,
    save_case,
    save_intake,
)
from app.services.data_loader import load_country_risk, load_dataset_manifest, load_occupation_risk
from app.services.evidence_store import link_evidence_to_case, save_evidence_files
from app.services.vector_store import vector_store


def _enrich_response(state: KYCState) -> dict:
    from app.services.copilot import build_case_context

    data = state.model_dump()
    data["agent_status"] = build_agent_status(state.audit_log, state.workflow_path)
    data["missing_fields"] = state.document_extraction.get("fields_missing", [])
    data["field_status"] = state.document_extraction.get("field_status", {})
    # Phase 6 — copilot context built dynamically (no DB migration)
    data["copilot_context"] = build_case_context(state)
    return data


def _stream_kyc(customer: CustomerInput, source: str, uploaded: list[dict] | None = None):
    intake_id = f"INT-{uuid.uuid4().hex[:8].upper()}"
    save_intake(intake_id, source, {**customer.model_dump(), "uploaded_count": len(uploaded or [])})

    def event_generator():
        final_state = None
        for event in orchestrator.run_with_events(customer):
            if event.get("type") == "complete":
                final_state = KYCState.model_validate(event["state"])
                if uploaded:
                    final_state.uploaded_evidence = uploaded
                if customer.evidence_ids:
                    link_evidence_to_case(customer.evidence_ids, final_state.case_id)
                save_case(final_state, source=source)
                link_intake_case(intake_id, final_state.case_id)
                event["state"] = _enrich_response(final_state)
                event["intake_id"] = intake_id
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    vector_store.seed_if_empty()
    yield


app = FastAPI(
    title="KYC Sentinel API",
    description="Agentic KYC Intelligence Platform — AMD Agentic AI Hackathon 2026",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    manifest = load_dataset_manifest()
    return {
        "status": "healthy",
        "service": "KYC Sentinel",
        "vector_db": "TF-IDF Vector Store",
        "groq_configured": bool(settings.groq_api_key),
        "data_sources": manifest.get("sources", []),
        "watchlist_entries": manifest.get("watchlist_count", 0),
        "amd_ready": True,
    }


@app.get("/api/datasets")
def get_dataset_info():
    return load_dataset_manifest()


@app.get("/api/agents")
def get_agents():
    return AGENT_REGISTRY


@app.get("/api/reference/countries")
def get_countries():
    return sorted(load_country_risk().keys())


@app.get("/api/reference/occupations")
def get_occupations():
    return sorted(load_occupation_risk().keys())


@app.get("/api/cases")
def get_cases():
    return list_cases()


@app.get("/api/cases/{case_id}")
def get_case_detail(case_id: str):
    state = get_case(case_id)
    if not state:
        raise HTTPException(status_code=404, detail="Case not found")
    return _enrich_response(state)


@app.post("/api/kyc/run/stream")
async def run_kyc_stream(
    name: str = Form(...),
    dob: str = Form(...),
    nationality: str = Form(...),
    occupation: str = Form(...),
    source_of_funds: str = Form(""),
    document_type: str = Form(""),
    id_number: str = Form(""),
    documents: list[UploadFile] = File(default=[]),
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Customer name is required")
    if not dob.strip():
        raise HTTPException(status_code=400, detail="Date of birth is required")

    file_tuples: list[tuple[str, bytes]] = []
    for doc in documents:
        if doc.filename:
            content = await doc.read()
            if content:
                file_tuples.append((doc.filename, content))

    uploaded = save_evidence_files(file_tuples) if file_tuples else []
    evidence_ids = [e["evidence_id"] for e in uploaded]

    customer = CustomerInput(
        name=name,
        dob=dob,
        nationality=nationality,
        occupation=occupation,
        source_of_funds=source_of_funds,
        document_type=document_type,
        id_number=id_number,
        evidence_ids=evidence_ids,
    )
    return _stream_kyc(customer, source="custom", uploaded=uploaded)


@app.post("/api/kyc/run")
async def run_kyc(
    name: str = Form(...),
    dob: str = Form(...),
    nationality: str = Form(...),
    occupation: str = Form(...),
    source_of_funds: str = Form(""),
    document_type: str = Form(""),
    id_number: str = Form(""),
    documents: list[UploadFile] = File(default=[]),
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Customer name is required")

    file_tuples: list[tuple[str, bytes]] = []
    for doc in documents:
        if doc.filename:
            content = await doc.read()
            if content:
                file_tuples.append((doc.filename, content))

    uploaded = save_evidence_files(file_tuples) if file_tuples else []
    evidence_ids = [e["evidence_id"] for e in uploaded]

    customer = CustomerInput(
        name=name,
        dob=dob,
        nationality=nationality,
        occupation=occupation,
        source_of_funds=source_of_funds,
        document_type=document_type,
        id_number=id_number,
        evidence_ids=evidence_ids,
    )
    intake_id = f"INT-{uuid.uuid4().hex[:8].upper()}"
    save_intake(intake_id, "custom", customer.model_dump())
    state = orchestrator.run(customer)
    state.uploaded_evidence = uploaded
    if evidence_ids:
        link_evidence_to_case(evidence_ids, state.case_id)
    save_case(state, source="custom")
    link_intake_case(intake_id, state.case_id)
    data = _enrich_response(state)
    data["intake_id"] = intake_id
    return data


@app.post("/api/cases/{case_id}/review")
def submit_review(case_id: str, review: HumanReviewInput):
    state = get_case(case_id)
    if not state:
        raise HTTPException(status_code=404, detail="Case not found")

    review.case_id = case_id
    from app.agents.human_review import human_review_agent
    from app.agents.audit import audit_report_agent

    state = human_review_agent(state, review)
    state = audit_report_agent(state)
    save_case(state, source="review")
    return _enrich_response(state)


@app.get("/api/cases/{case_id}/audit")
def get_audit_report(case_id: str):
    state = get_case(case_id)
    if not state:
        raise HTTPException(status_code=404, detail="Case not found")
    report = state.decision.get("audit_report")
    if not report:
        raise HTTPException(status_code=404, detail="Audit report not found")
    return report


@app.post("/api/cases/{case_id}/copilot")
def ask_copilot(case_id: str, body: dict):
    """Read-only investigation Q&A. Logs the question (not the answer) for audit."""
    from datetime import datetime, timezone
    from app.services.copilot import answer_question

    state = get_case(case_id)
    if not state:
        raise HTTPException(status_code=404, detail="Case not found")

    question = (body or {}).get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="A question is required")

    result = answer_question(state, question)

    # Part 11 — log the question + timestamp (never the answer); does not alter findings.
    state.copilot_queries.append({
        "question": question,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    save_case(state, source="copilot")

    return {"answer": result["answer"], "source": result["source"]}

# Trigger reload comment to force uvicorn refresh
