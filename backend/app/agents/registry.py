AGENT_REGISTRY = [
    {"id": "orchestrator",                    "name": "Orchestrator Agent",                     "phase": "routing",    "description": "Routes dynamic investigation workflow"},
    {"id": "intake",                           "name": "Customer Intake Agent",                  "phase": "intake",     "description": "Accepts and structures onboarding request"},
    {"id": "document_extraction",             "name": "Document Extraction Agent",              "phase": "intake",     "description": "Parses fields and scores extraction confidence"},
    {"id": "groq_verification",               "name": "Groq Verification Agent",                "phase": "intake",     "description": "AI-powered profile plausibility check via Groq"},
    {"id": "normalization",                   "name": "Profile Normalization Agent",             "phase": "processing", "description": "Standardizes names, dates, and addresses"},
    {"id": "indian_document_verification",    "name": "Indian Document Verification Agent",     "phase": "verification","description": "XGBoost ML: verifies Indian KYC docs (Aadhaar/PAN/Passport/Voter ID/DL/Passbook)"},
    {"id": "entity_resolution",               "name": "Entity Resolution Agent",                "phase": "screening",  "description": "Reduces false positives via fuzzy matching"},
    {"id": "compliance_screening",            "name": "Compliance Screening Agent",             "phase": "screening",  "description": "Sanctions, watchlist, and PEP screening"},
    {"id": "adverse_media",                   "name": "Adverse Media Agent",                    "phase": "screening",  "description": "Analyzes negative news and regulatory notices"},
    {"id": "evidence_validation",             "name": "Evidence Validation Agent",              "phase": "screening",  "description": "Groq-powered semantic document content validation"},
    {"id": "financial_profiling",             "name": "Financial Profiling Agent",              "phase": "risk",       "description": "Assesses occupation, funds, and country risk"},
    {"id": "confidence",                      "name": "Confidence Agent",                       "phase": "confidence", "description": "Aggregates verification confidence across agents"},
    {"id": "risk_scoring",                    "name": "Risk Scoring Agent",                     "phase": "risk",       "description": "Aggregates all risk signals into a score (XGBoost + rules)"},
    {"id": "edd_trigger",                     "name": "EDD Trigger Agent",                      "phase": "edd",        "description": "Evaluates whether Enhanced Due Diligence is required"},
    {"id": "enhanced_due_diligence",          "name": "Enhanced Due Diligence Agent",           "phase": "edd",        "description": "Deeper investigation of high-risk profiles (conditional)"},
    {"id": "edd_summary",                     "name": "EDD Summary Agent",                      "phase": "edd",        "description": "Summarizes enhanced due diligence findings (conditional)"},
    {"id": "consistency",                     "name": "Consistency Agent",                      "phase": "consistency","description": "Detects cross-signal contradictions in the profile"},
    {"id": "risk_breakdown",                  "name": "Risk Breakdown Agent",                   "phase": "risk",       "description": "Decomposes the risk score into per-factor contributions"},
    {"id": "explainability",                  "name": "Explainability Agent",                   "phase": "decision",   "description": "Generates human-readable reasoning"},
    {"id": "decision",                        "name": "Decision Agent",                         "phase": "decision",   "description": "Produces APPROVE / REVIEW / ESCALATE"},
    {"id": "copilot",                         "name": "Compliance Copilot Agent",               "phase": "decision",   "description": "Generates an investigation-ready executive summary"},
    {"id": "human_review",                    "name": "Human Review Agent",                     "phase": "review",     "description": "Compliance officer intervention"},
    {"id": "audit_report",                    "name": "Audit Report Agent",                     "phase": "audit",      "description": "Generates auditable decision report"},
]

AGENT_NAME_TO_ID = {a["name"]: a["id"] for a in AGENT_REGISTRY}


def build_agent_status(audit_log: list, workflow_path: list[str]) -> list[dict]:
    executed_names = {e.agent for e in audit_log}

    status_list = []
    for agent in AGENT_REGISTRY:
        ran = agent["name"] in executed_names or agent["id"] in workflow_path
        # Agents that may legitimately be skipped
        conditional = agent["id"] in (
            "evidence_validation", "human_review",
            "entity_resolution_deep", "entity_resolution_pep",
            "enhanced_due_diligence", "edd_summary",
        )
        status_list.append(
            {
                **agent,
                "status": "executed" if ran else ("skipped" if conditional else "not_run"),
                "executed": ran,
            }
        )
    return status_list
