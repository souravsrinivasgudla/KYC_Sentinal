const API_BASE = '/api'

export interface CustomCustomer {
  name: string
  dob: string
  nationality: string
  occupation: string
  source_of_funds: string
  document_type: string
  id_number: string
}

export interface RiskContribution {
  factor: string
  impact: number
  category?: string
}

export interface ConsistencyIssue {
  type: string
  severity: 'low' | 'medium' | 'high'
  description: string
}

export interface AgentEvent {
  agent: string
  action: string
  timestamp: string
  details: Record<string, unknown>
}

export interface AgentStatus {
  id: string
  name: string
  phase: string
  description: string
  status: 'executed' | 'skipped' | 'not_run'
  executed: boolean
}

export interface FieldStatus {
  value: string
  provided: boolean
  required: boolean
  confidence: number
  label: string
  status: 'ok' | 'missing' | 'low_confidence'
}

export interface StepEvent {
  type: 'step' | 'complete'
  step_id: string
  step_name: string
  step_index: number
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'warning' | 'rejected' | 'info'
  message: string
  case_id?: string
  missing_fields?: string[]
  has_missing?: boolean
  doc_type_mismatch?: boolean
  declared_doc_type?: string
  detected_doc_type?: string
}

export interface StoredCase {
  case_id: string
  created_at: string
  source: string
  customer_name: string
  risk_score: number
  risk_level: string
  decision: string
  final_status?: string | null
  requires_review: boolean
  human_reviewed: boolean
  missing_fields: string[]
  overall_confidence?: number
  top_risk_drivers?: RiskContribution[]
  edd_triggered?: boolean
  consistency_score?: number
}

export interface UploadedEvidence {
  evidence_id: string
  original_filename: string
  extraction_method: string
  is_image: boolean
}

export interface KYCResult {
  case_id: string
  customer_profile: Record<string, string>
  uploaded_evidence: UploadedEvidence[]
  groq_verification: Record<string, unknown>
  document_extraction: Record<string, unknown> & {
    field_status?: Record<string, FieldStatus>
    fields_missing?: string[]
  }
  entity_resolution: Record<string, unknown>
  screening_results: Record<string, unknown>
  adverse_media: Record<string, unknown>
  financial_profile: Record<string, unknown>
  evidence_validation: {
    validation_passed?: boolean
    ml_validation_passed?: boolean
    groq_validation_passed?: boolean
    identity_verified?: boolean
    summary?: string
    critical_issues?: string[]
    has_proof_of_identity?: boolean
    has_proof_of_address?: boolean
    doc_types_detected?: string[]
    ml_classification?: {
      ml_used: boolean
      doc_types_detected: string[]
      valid_count: number
      invalid_count: number
      all_valid: boolean
      any_valid: boolean
      has_poi: boolean
      has_poa: boolean
      avg_completeness: number
      avg_trust_signal: number
      validity_issues: string[]
      per_document: Array<{
        evidence_id: string
        filename: string
        doc_type: string
        doc_type_display: string
        doc_type_confidence: number
        is_valid: boolean
        validity_confidence: number
        validity_issues: string[]
        doc_number: string
        kyc_purpose: { poi: boolean; poa: boolean }
        completeness_score: number
        trust_signal_score: number
        all_type_probabilities: Record<string, number>
        groq_extracted_fields?: Record<string, string | boolean | number>
        groq_notes?: string
        groq_integrity_score?: number
        groq_profile_match?: Record<string, unknown>
      }>
    }
  }
  risk_assessment: {
    risk_score: number
    risk_level: string
    scoring_method?: string
    rule_score?: number
    breakdown: { signal: string; points: number; source?: string; ml_class?: string }[]
    ml_result?: {
      ml_used: boolean
      ml_risk_class: number
      ml_risk_level: string
      ml_risk_score: number
      ml_confidence: number
      ml_probabilities: { Low: number; Medium: number; High: number }
    }
  }
  explanation: {
    decision_hint: string
    reasons: string[]
    narrative: string
    groq_powered?: boolean
    urgency?: string
    confidence_commentary?: string
    overall_confidence?: number
    risk_drivers_commentary?: string
    top_risk_drivers?: RiskContribution[]
    edd_commentary?: string
    edd_triggered?: boolean
    consistency_commentary?: string
    consistency_score?: number
    id_mismatch?: {
      declared: string
      extracted: string
      reason: string
      short_reason: string
      severity: string
    } | null
  }
  decision: {
    status: string
    risk_score: number
    requires_human_review: boolean
    audit_report?: Record<string, unknown>
    final_status?: string
    human_reviewed?: boolean
    document_rejected?: boolean
    rejection_reasons?: string[]
    reasons?: string[]
    urgency?: 'immediate' | 'standard' | 'low'
    groq_powered?: boolean
    id_mismatch?: {
      detected: boolean
      declared: string
      extracted: string
      reason: string
    } | null
  }
  human_review: Record<string, unknown>
  audit_log: AgentEvent[]
  workflow_path: string[]
  agent_status: AgentStatus[]
  // Phase 2 — confidence framework (optional; safe defaults for legacy cases)
  overall_confidence?: number
  agent_confidences?: Record<string, number>
  confidence_summary?: string
  // Phase 3 — risk contribution breakdown (optional; safe defaults for legacy cases)
  risk_contributions?: RiskContribution[]
  top_risk_drivers?: RiskContribution[]
  risk_breakdown_summary?: string
  // Phase 4 — enhanced due diligence (optional; safe defaults for legacy cases)
  edd_triggered?: boolean
  edd_reasons?: string[]
  edd_findings?: string[]
  edd_summary?: string
  // Phase 5 — cross-signal consistency analysis (optional; safe defaults for legacy cases)
  consistency_score?: number
  consistency_summary?: string
  consistency_issues?: ConsistencyIssue[]
  // Phase 6 — compliance investigation copilot (optional; safe defaults for legacy cases)
  executive_summary?: string
  copilot_context?: Record<string, unknown>
  missing_fields?: string[]
  field_status?: Record<string, FieldStatus>
  document_rejected?: boolean
  document_verdict?: {
    verdict: 'VERIFIED' | 'NEEDS_REVIEW' | 'REJECTED'
    summary: string
    declared_doc_type?: string
    detected_doc_type?: string
    document_type_mismatch?: boolean
    mismatch_severity?: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'
    doc_type_match?: {
      declared_doc_type: string
      detected_doc_type: string
      document_type_mismatch: boolean
      mismatch_severity: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'
      points: number
      reason: string
      short_reason: string
    }
    rejection_reasons: string[]
    verified_count: number
    rejected_count: number
    review_count: number
    total_docs: number
    has_poi: boolean
    has_poa: boolean
    verified_types: string[]
    pipeline_blocked: boolean
    id_mismatch?: {
      declared: string
      extracted: string
      reason: string
      short_reason: string
      severity: string
    } | null
    per_document: Array<{
      evidence_id: string
      filename: string
      doc_type: string
      doc_type_display: string
      doc_type_confidence: number
      doc_number: string
      is_valid_ml: boolean
      validity_confidence: number
      verdict: 'VERIFIED' | 'NEEDS_REVIEW' | 'REJECTED'
      verdict_reason: string
      validity_issues: string[]
      kyc_purpose: { poi: boolean; poa: boolean }
      completeness_score: number
      trust_signal_score: number
      groq_extracted_fields?: Record<string, string | boolean | number>
      groq_notes?: string
      groq_integrity_score?: number
      groq_profile_match?: Record<string, unknown>
    }>
  }
}

export async function fetchCases(): Promise<StoredCase[]> {
  const res = await fetch(`${API_BASE}/cases`)
  if (!res.ok) throw new Error('Failed to fetch cases')
  return res.json()
}

export async function fetchCase(caseId: string, signal?: AbortSignal): Promise<KYCResult> {
  const res = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId.trim())}`, { signal })
  if (!res.ok) throw new Error('Case not found')
  return res.json()
}

export async function fetchCountries(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/reference/countries`)
  if (!res.ok) throw new Error('Failed to fetch countries')
  return res.json()
}

export async function fetchOccupations(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/reference/occupations`)
  if (!res.ok) throw new Error('Failed to fetch occupations')
  return res.json()
}

export async function runKYCStream(
  customer: CustomCustomer,
  documents: File[],
  onStep: (step: StepEvent) => void,
): Promise<KYCResult> {
  const form = new FormData()
  form.append('name', customer.name)
  form.append('dob', customer.dob)
  form.append('nationality', customer.nationality)
  form.append('occupation', customer.occupation)
  form.append('source_of_funds', customer.source_of_funds)
  form.append('document_type', customer.document_type)
  form.append('id_number', customer.id_number)
  documents.forEach((f) => form.append('documents', f))

  const res = await fetch(`${API_BASE}/kyc/run/stream`, { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'KYC stream failed')
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResult: KYCResult | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = JSON.parse(line.slice(6))
      if (data.type === 'step') onStep(data as StepEvent)
      else if (data.type === 'complete') {
        finalResult = {
          ...(data.state as KYCResult),
          document_rejected: data.document_rejected,
          document_verdict: data.document_verdict,
        }
      }
    }
  }

  if (!finalResult) throw new Error('Stream ended without result')
  return finalResult
}

export async function submitReview(
  caseId: string,
  action: string,
  comment: string,
  reviewer: string,
): Promise<KYCResult> {
  const res = await fetch(`${API_BASE}/cases/${caseId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ case_id: caseId, action, comment, reviewer }),
  })
  if (!res.ok) throw new Error('Review submission failed')
  return res.json()
}

export async function askCopilot(
  caseId: string,
  question: string,
): Promise<{ answer: string; source: string }> {
  const res = await fetch(`${API_BASE}/cases/${caseId}/copilot`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) throw new Error('Copilot request failed')
  return res.json()
}

export async function checkHealth(): Promise<{ status: string; groq_configured: boolean }> {
  const res = await fetch(`${API_BASE}/health`)
  return res.json()
}
