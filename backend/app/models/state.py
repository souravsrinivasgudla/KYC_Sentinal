from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class CustomerInput(BaseModel):
    name: str
    dob: str
    nationality: str
    occupation: str
    source_of_funds: str = ""
    document_type: str = ""
    id_number: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class CustomKYCRequest(BaseModel):
    name: str
    dob: str
    nationality: str
    occupation: str
    source_of_funds: str = ""
    document_type: str = ""
    id_number: str = ""


class AgentEvent(BaseModel):
    agent: str
    action: str
    timestamp: str
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[int] = None


class HumanReviewInput(BaseModel):
    case_id: str
    action: Literal["approve", "override", "escalate"]
    comment: str = ""
    reviewer: str = "Compliance Analyst"


class KYCState(BaseModel):
    case_id: str = ""
    customer_profile: dict[str, Any] = Field(default_factory=dict)
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)
    groq_verification: dict[str, Any] = Field(default_factory=dict)
    evidence_validation: dict[str, Any] = Field(default_factory=dict)
    document_extraction: dict[str, Any] = Field(default_factory=dict)
    # XGBoost Indian document verification result
    document_verdict: dict[str, Any] = Field(default_factory=dict)
    entity_resolution: dict[str, Any] = Field(default_factory=dict)
    screening_results: dict[str, Any] = Field(default_factory=dict)
    adverse_media: dict[str, Any] = Field(default_factory=dict)
    financial_profile: dict[str, Any] = Field(default_factory=dict)
    risk_assessment: dict[str, Any] = Field(default_factory=dict)
    explanation: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] = Field(default_factory=dict)
    human_review: dict[str, Any] = Field(default_factory=dict)
    audit_log: list[AgentEvent] = Field(default_factory=list)
    workflow_path: list[str] = Field(default_factory=list)
    # Phase 1 parallel execution metadata
    parallel_execution: bool = False
    agent_timings: list[dict[str, Any]] = Field(default_factory=list)
    parallel_errors: list[dict[str, Any]] = Field(default_factory=list)
    # Phase 2 confidence framework (separate from risk; never affects decisions)
    overall_confidence: float = 0.0
    agent_confidences: dict[str, float] = Field(default_factory=dict)
    confidence_summary: str = ""
    # Phase 3 risk contribution breakdown (explainability only; never changes score)
    risk_contributions: list[dict[str, Any]] = Field(default_factory=list)
    top_risk_drivers: list[dict[str, Any]] = Field(default_factory=list)
    risk_breakdown_summary: str = ""
    # Phase 4 enhanced due diligence (adaptive investigation; never changes decision)
    edd_triggered: bool = False
    edd_reasons: list[str] = Field(default_factory=list)
    edd_findings: list[str] = Field(default_factory=list)
    edd_summary: str = ""
    # Phase 5 cross-signal consistency analysis (advisory only; never changes decision)
    consistency_issues: list[dict[str, Any]] = Field(default_factory=list)
    consistency_summary: str = ""
    consistency_score: float = 1.0
    # Phase 6 compliance investigation copilot (read-only; never changes decision)
    executive_summary: str = ""
    copilot_queries: list[dict[str, Any]] = Field(default_factory=list)
