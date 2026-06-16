import { CheckCircle, AlertTriangle, Loader2, SkipForward, Circle, Bot, XCircle } from 'lucide-react'
import { StepEvent } from '../api'

interface Props {
  steps: StepEvent[]
  currentStepId: string | null
  isRunning: boolean
}

const FIELD_LABELS: Record<string, string> = {
  source_of_funds: 'Source of Funds',
  id_number: 'ID Number',
  name: 'Full Name',
  dob: 'Date of Birth',
  nationality: 'Country',
  occupation: 'Occupation',
}

/** Canonical pipeline order — defines the display sequence */
const STEP_ORDER = [
  'orchestrator',
  'intake',
  'document_extraction',
  'groq_verification',
  'normalization',
  'indian_document_verification',
  'entity_resolution',
  'entity_resolution_deep',
  'compliance_screening',
  'entity_resolution_pep',
  'adverse_media',
  'evidence_validation',
  'financial_profiling',
  'confidence',
  'risk_scoring',
  'edd_trigger',
  'enhanced_due_diligence',
  'edd_summary',
  'consistency',
  'risk_breakdown',
  'explainability',
  'decision',
  'human_review',
  'audit_report',
]

function stepOrder(step: StepEvent): number {
  const base = step.step_id.replace(/_deep$/, '').replace(/_pep$/, '')
  const idx = STEP_ORDER.indexOf(step.step_id)
  if (idx >= 0) return idx
  const baseIdx = STEP_ORDER.indexOf(base)
  return baseIdx >= 0 ? baseIdx + 0.5 : 999
}

function StepIcon({ status }: { status: StepEvent['status'] | 'rejected' }) {
  if (status === 'running')  return <Loader2 size={15} className="spin" />
  if (status === 'completed') return <CheckCircle size={15} />
  if (status === 'warning')  return <AlertTriangle size={15} />
  if (status === 'skipped')  return <SkipForward size={15} />
  if (status === 'rejected') return <XCircle size={15} />
  return <Circle size={13} />
}

function isOrchestratorEvent(step: StepEvent) {
  // Main orchestrator events plus parallel-phase notes (orchestrator_parallel_*).
  return step.step_id === 'orchestrator' || step.step_id.startsWith('orchestrator_')
}

export default function StepFlow({ steps, currentStepId, isRunning }: Props) {
  if (!steps.length) return null

  // Deduplicate: for each step_id+step_name, keep the latest event.
  // Then sort by canonical pipeline order.
  const dedupMap = new Map<string, StepEvent>()
  for (const step of steps) {
    const key = `${step.step_id}::${step.step_name}`
    dedupMap.set(key, step)
  }

  // Separate orchestrator routing notes from main agent steps
  const allSteps = Array.from(dedupMap.values())
  const mainSteps = allSteps
    .filter((s) => !isOrchestratorEvent(s))
    .sort((a, b) => stepOrder(a) - stepOrder(b))

  // Orchestrator routing annotations (mid-pipeline routing messages)
  const orchestratorNotes = allSteps.filter(
    (s) => isOrchestratorEvent(s) && s.status !== 'completed' && s.status !== 'running'
  )

  // Re-number sequentially after sort
  const numbered = mainSteps.map((s, i) => ({ ...s, step_index: i + 1 }))

  const completedCount = numbered.filter((s) => s.status === 'completed' || s.status === 'warning').length
  const totalCount = numbered.filter((s) => s.status !== 'skipped').length

  return (
    <div className="nf-card step-flow-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <h3 style={{ margin: 0 }}>Verification Pipeline</h3>
        {totalCount > 0 && (
          <span style={{ fontSize: '0.7rem', color: 'var(--nf-dim)' }}>
            {completedCount}/{totalCount} complete
          </span>
        )}
      </div>
      <p className="step-flow-subtitle">
        {isRunning ? 'Agents executing in sequence...' : 'Pipeline complete'}
      </p>

      <div className="step-flow">
        {numbered.map((step, i) => {
          const isActive = step.status === 'running' || step.step_id === currentStepId
          const isLast = i === numbered.length - 1
          return (
            <div
              key={`${step.step_id}::${step.step_name}`}
              className={`step-item ${step.status} ${isActive ? 'active' : ''}`}
            >
              <div className="step-indicator-col">
                <div className={`step-indicator ${step.status}`}>
                  <StepIcon status={step.status as any} />
                </div>
                {!isLast && (
                  <div
                    className={`step-connector ${
                      step.status === 'completed' || step.status === 'warning' ? 'done' :
                      step.status === 'rejected' ? 'rejected' : ''
                    }`}
                  />
                )}
              </div>

              <div className="step-body">
                <div className="step-header">
                  <span className="step-index">Step {step.step_index}</span>
                  <span className="step-name">{step.step_name}</span>
                  {step.status === 'rejected' && (
                    <span className="step-rejected-badge">REJECTED</span>
                  )}
                </div>
                <p className="step-message">{step.message}</p>

                {/* Document rejection reasons */}
                {(step as any).rejection_reasons && (step as any).rejection_reasons.length > 0 && (
                  <div className="step-rejection-block">
                    {((step as any).rejection_reasons as string[]).slice(0, 4).map((r: string, j: number) => (
                      <div key={j} className="step-rejection-reason">
                        <XCircle size={10} /> {r}
                      </div>
                    ))}
                  </div>
                )}

                {step.missing_fields && step.missing_fields.length > 0 && (
                  <div className="step-missing">
                    <AlertTriangle size={12} />
                    Missing: {step.missing_fields.map((f) => FIELD_LABELS[f] || f).join(', ')}
                  </div>
                )}

                {(step as any).doc_type_mismatch && (
                  <div className="step-missing">
                    <AlertTriangle size={12} />
                    Declared document type does not match uploaded document.
                    {((step as any).declared_doc_type || (step as any).detected_doc_type) && (
                      <> ({(step as any).declared_doc_type || '—'} → {(step as any).detected_doc_type || '—'})</>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Orchestrator routing annotations */}
      {orchestratorNotes.length > 0 && (
        <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--nf-dim)', marginBottom: '0.4rem', display: 'flex', alignItems: 'center', gap: 4 }}>
            <Bot size={11} /> Orchestrator Notes
          </div>
          {orchestratorNotes.map((n, i) => (
            <div key={i} style={{ fontSize: '0.75rem', color: 'var(--nf-muted)', padding: '0.25rem 0', display: 'flex', gap: '0.4rem', alignItems: 'flex-start' }}>
              <span style={{ color: 'var(--nf-red)', fontSize: '0.6rem', marginTop: 2 }}>▸</span>
              {n.message}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
