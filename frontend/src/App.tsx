import { useCallback, useEffect, useState } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { CheckCircle, AlertTriangle, XCircle, Shield } from 'lucide-react'
import {
  CustomCustomer,
  KYCResult,
  StepEvent,
  StoredCase,
  FieldStatus,
  fetchCountries,
  fetchOccupations,
  fetchCases,
  runKYCStream,
} from './api'
import CustomKYCForm from './components/CustomKYCForm'
import StepFlow from './components/StepFlow'
import CopilotPanel from './components/CopilotPanel'
import NavBar from './components/NavBar'
import HumanReviewPanel from './components/HumanReviewPanel'
import ProfilesPage from './pages/ProfilesPage'
import ProfileDetailPage from './pages/ProfileDetailPage'
import DashboardPage from './pages/DashboardPage'
import AboutPage from './pages/AboutPage'
import { decisionClass } from './utils/decision'
import { countryLabel } from './country'
import { validateDocumentNumber } from './documentTypes'
import {
  AGENT_CONFIDENCE_LABELS,
  AGENT_CONFIDENCE_ORDER,
  confidenceBand,
  confidenceExplanation,
  confidenceIcon,
  confidenceLabel,
  confidencePct,
  hasConfidence,
} from './utils/confidence'
import { formatImpact, impactBarWidth, maxAbsImpact } from './utils/riskBreakdown'
import {
  consistencyBand,
  consistencyIcon,
  consistencyLabel,
  consistencyPct,
  sortBySeverity,
} from './utils/consistency'

type Tab = 'overview' | 'pipeline' | 'documents' | 'evidence' | 'audit' | 'copilot'

const EMPTY: CustomCustomer = {
  name: '', dob: '', nationality: '', occupation: '', source_of_funds: '', document_type: '', id_number: '',
}

const PROFILE_KEYS = ['name', 'dob', 'nationality', 'occupation', 'source_of_funds', 'document_type', 'id_number']

// Display labels for profile fields when the backend field_status label is absent.
const PROFILE_LABELS: Record<string, string> = {
  nationality: 'Country',
  document_type: 'Document Type',
  id_number: 'Document Number',
}

const RECENT_LIMIT = 10

function DecisionIcon({ status }: { status: string }) {
  if (status === 'APPROVE') return <CheckCircle size={32} />
  if (status === 'REVIEW') return <AlertTriangle size={32} />
  return <XCircle size={32} />
}

export default function App() {
  const location = useLocation()
  const [countries, setCountries] = useState<string[]>([])
  const [occupations, setOccupations] = useState<string[]>([])
  const [storedCases, setStoredCases] = useState<StoredCase[]>([])
  const [form, setForm] = useState<CustomCustomer>(EMPTY)
  const [documents, setDocuments] = useState<File[]>([])
  const [result, setResult] = useState<KYCResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState<StepEvent[]>([])
  const [currentStepId, setCurrentStepId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('overview')
  const [navScrolled, setNavScrolled] = useState(false)

  const refreshHistory = useCallback(() => {
    fetchCases().then(setStoredCases).catch(() => {})
  }, [])

  useEffect(() => {
    fetchCountries().then(setCountries).catch(() => {})
    fetchOccupations().then(setOccupations).catch(() => {})
    refreshHistory()
    const onScroll = () => setNavScrolled(window.scrollY > 40)
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [refreshHistory])

  useEffect(() => {
    setNavScrolled(false)
  }, [location.pathname])

  const handleStep = useCallback((step: StepEvent) => {
    if (step.status === 'running') setCurrentStepId(step.step_id)
    setSteps((prev) => {
      // Find by step_id AND step_name to handle conditional repeated agents
      // (entity_resolution_deep, entity_resolution_pep share the same base step_id prefix)
      const idx = prev.findIndex(
        (s) => s.step_id === step.step_id && s.step_name === step.step_name
      )
      if (idx >= 0) {
        // Update in-place, preserving order
        const next = [...prev]
        next[idx] = step
        return next
      }
      // New step: append in arrival order — re-index sequentially
      const appended = [...prev, step]
      return appended.map((s, i) => ({ ...s, step_index: i + 1 }))
    })
  }, [])

  const handleVerify = useCallback(async () => {
    if (!form.name.trim() || !form.dob || !form.nationality.trim() || !form.occupation.trim()) {
      setError('Please complete all required fields.')
      return
    }
    if (!form.document_type.trim()) {
      setError('Please select the document type you are submitting.')
      return
    }
    const docFormatError = validateDocumentNumber(form.document_type, form.id_number)
    if (docFormatError) {
      setError(docFormatError)
      return
    }
    setLoading(true)
    setResult(null)
    setSteps([])
    setError('')
    setTab('pipeline')
    try {
      const res = await runKYCStream(form, documents, handleStep)
      setResult(res)
      // Auto-switch to documents tab if document was rejected
      setTab(res.document_rejected ? 'documents' : 'overview')
      refreshHistory()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Verification failed')
    } finally {
      setLoading(false)
      setCurrentStepId(null)
    }
  }, [form, documents, handleStep, refreshHistory])

  const handleReview = async (updated: KYCResult) => {
    setResult(updated)
    refreshHistory()
  }

  const fieldStatus = result?.field_status || result?.document_extraction?.field_status as Record<string, FieldStatus> | undefined
  const dc = result ? decisionClass(result.decision.status) : ''
  const recentCases = storedCases.slice(0, RECENT_LIMIT)

  return (
    <>
      <NavBar navScrolled={navScrolled} />

      <Routes>
        <Route
          path="/profiles/:caseId"
          element={<ProfileDetailPage onRefresh={refreshHistory} />}
        />
        <Route
          path="/dashboard"
          element={<DashboardPage />}
        />
        <Route
          path="/about"
          element={<AboutPage />}
        />
        <Route
          path="/profiles"
          element={<ProfilesPage cases={storedCases} onRefresh={refreshHistory} />}
        />
        <Route
          path="/"
          element={
            <>
      <section className="nf-hero">
        <div className="nf-hero-content">
          <h1>Know Your <span>Customer</span></h1>
          <p>
            Agentic AI compliance platform with Groq-powered document validation,
            sanctions screening, and human-in-the-loop review.
          </p>
        </div>
      </section>

      <main className="nf-main">
        {recentCases.length > 0 && (
          <section className="nf-row">
            <h2 className="nf-section-title">Recent Verifications</h2>
            <div className="nf-row-scroll">
              {recentCases.map((c) => (
                <Link
                  key={c.case_id}
                  to={`/profiles/${c.case_id}`}
                  className={`nf-poster ${result?.case_id === c.case_id ? 'active' : ''}`}
                >
                  <div className={`nf-poster-top ${decisionClass(c.decision)}`}>{c.risk_score}</div>
                  <div className="nf-poster-body">
                    <div className="nf-poster-name">{c.customer_name}</div>
                    <div className="nf-poster-meta">{c.decision} · {c.case_id}</div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}

        {error && <div className="nf-error">{error}</div>}

        <div className="nf-grid-2">
          <div>
            <h2 className="nf-section-title">New Verification</h2>
            <div className="nf-form-card">
              <CustomKYCForm
                form={form}
                countries={countries}
                occupations={occupations}
                documents={documents}
                onChange={setForm}
                onDocumentsChange={setDocuments}
                onSubmit={handleVerify}
                loading={loading}
              />
            </div>
          </div>

          <div className="nf-results">
            {(loading || steps.length > 0) && (
              <StepFlow steps={steps} currentStepId={currentStepId} isRunning={loading} />
            )}

            {!result && !loading && !steps.length && (
              <div className="nf-card nf-empty">
                <Shield size={48} style={{ opacity: 0.2, margin: '0 auto 1rem' }} />
                <p>Submit customer details and proof documents to begin verification.</p>
              </div>
            )}

            {result && !loading && (
              <>
                <div className={`nf-decision-hero ${dc}`}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <DecisionIcon status={result.decision.status} />
                    <div>
                      <div className="nf-decision-label">Decision</div>
                      <div className="nf-decision-value">{result.decision.final_status || result.decision.status}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--nf-dim)', marginTop: 4 }}>{result.case_id}</div>
                    </div>
                  </div>
                  <div className="nf-score" style={{ color: dc === 'approve' ? 'var(--nf-success)' : dc === 'review' ? 'var(--nf-warning)' : 'var(--nf-red)' }}>
                    {result.risk_assessment.risk_score}
                  </div>
                </div>

                {/* Overall confidence card (Part 5) — separate from risk */}
                {hasConfidence(result.overall_confidence) && (() => {
                  const band = confidenceBand(result.overall_confidence)
                  return (
                    <div className={`nf-confidence-card ${band}`}>
                      <div className="nf-confidence-head">
                        <span className="nf-confidence-label">Overall Confidence</span>
                        <span className="nf-confidence-pct">{confidencePct(result.overall_confidence)}%</span>
                      </div>
                      <div className="nf-confidence-bar">
                        <div className="nf-confidence-fill" style={{ width: `${confidencePct(result.overall_confidence)}%` }} />
                      </div>
                      <div className="nf-confidence-status">
                        {confidenceIcon(band)} {confidenceLabel(band)}
                      </div>
                      <p className="nf-confidence-explain">
                        {result.confidence_summary || confidenceExplanation(band)}
                      </p>
                    </div>
                  )
                })()}

                {/* Top Risk Drivers (Part 7) — readable at a glance near the decision */}
                {(result.top_risk_drivers?.length ?? 0) > 0 && (
                  <div className="nf-top-drivers">
                    <div className="nf-top-drivers-title">Top Risk Drivers</div>
                    <ol className="nf-top-drivers-list">
                      {result.top_risk_drivers!.map((d, i) => (
                        <li key={i}>
                          <span>{d.factor}</span>
                          <span className="nf-top-drivers-impact">{formatImpact(d.impact)}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}

                {/* Enhanced Due Diligence card (Part 8) — only when triggered */}
                {result.edd_triggered && (
                  <div className="nf-edd-card">
                    <div className="nf-edd-title">
                      <AlertTriangle size={16} /> Enhanced Due Diligence
                    </div>
                    {(result.edd_reasons?.length ?? 0) > 0 && (
                      <div className="nf-edd-section">
                        <span className="nf-edd-label">Triggered by</span>
                        <ul>{result.edd_reasons!.map((r, i) => <li key={i}>{r}</li>)}</ul>
                      </div>
                    )}
                    {(result.edd_findings?.length ?? 0) > 0 && (
                      <div className="nf-edd-section">
                        <span className="nf-edd-label">Findings</span>
                        <ul>{result.edd_findings!.map((f, i) => <li key={i}>{f}</li>)}</ul>
                      </div>
                    )}
                    {result.edd_summary && (
                      <p className="nf-edd-summary">{result.edd_summary}</p>
                    )}
                  </div>
                )}

                {/* Profile Consistency card + findings (Parts 7 & 8) */}
                {result.consistency_summary && (() => {
                  const band = consistencyBand(result.consistency_score)
                  const issues = sortBySeverity(result.consistency_issues || [])
                  return (
                    <div className={`nf-consistency-card ${band}`}>
                      <div className="nf-consistency-head">
                        <span className="nf-consistency-label">Profile Consistency</span>
                        <span className="nf-consistency-pct">{consistencyPct(result.consistency_score)}%</span>
                      </div>
                      <div className="nf-consistency-status">
                        {consistencyIcon(band)} {consistencyLabel(band)}
                        {issues.length > 0 && (
                          <span className="nf-consistency-count">{issues.length} issue{issues.length !== 1 ? 's' : ''}</span>
                        )}
                      </div>
                      {issues.length > 0 && (
                        <div className="nf-consistency-findings">
                          {issues.map((iss, i) => (
                            <div key={i} className={`nf-consistency-finding ${iss.severity}`}>
                              <span className={`nf-consistency-sev ${iss.severity}`}>{iss.severity.toUpperCase()}</span>
                              <span>{iss.description}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })()}

                {result.missing_fields && result.missing_fields.length > 0 && (
                  <div className="nf-banner-warn">
                    <AlertTriangle size={18} />
                    <div>
                      <strong>Incomplete profile</strong>
                      <p style={{ fontSize: '0.85rem', marginTop: 4 }}>Missing: {result.missing_fields.map((f) => f.replace(/_/g, ' ')).join(', ')}</p>
                    </div>
                  </div>
                )}

                {/* Document Rejection Banner */}
                {result.document_rejected && result.document_verdict && (
                  <div className="nf-banner-rejected">
                    <XCircle size={22} style={{ flexShrink: 0, marginTop: 2 }} />
                    <div style={{ flex: 1 }}>
                      <strong style={{ fontSize: '0.95rem' }}>Document Verification REJECTED</strong>
                      <p style={{ fontSize: '0.85rem', marginTop: 4, color: 'rgba(255,120,120,0.9)' }}>
                        {result.document_verdict.summary}
                      </p>
                      {result.document_verdict.rejection_reasons.length > 0 && (
                        <ul style={{ marginTop: '0.5rem', paddingLeft: '1rem', fontSize: '0.8rem', color: 'rgba(255,180,180,0.85)' }}>
                          {result.document_verdict.rejection_reasons.slice(0, 5).map((r, i) => (
                            <li key={i} style={{ marginBottom: '0.2rem' }}>{r}</li>
                          ))}
                        </ul>
                      )}
                      <p style={{ fontSize: '0.75rem', marginTop: '0.5rem', color: 'rgba(255,120,120,0.7)' }}>
                        Pipeline short-circuited — remaining agents were skipped. Case escalated for human review.
                      </p>
                    </div>
                  </div>
                )}

                {/* ID number mismatch — entered vs document */}
                {(result.decision.id_mismatch?.detected || result.document_verdict?.id_mismatch || result.explanation?.id_mismatch) && (
                  <div className="nf-banner-rejected" style={{ borderColor: 'rgba(255,165,0,0.6)', background: 'rgba(255,165,0,0.08)' }}>
                    <AlertTriangle size={18} style={{ flexShrink: 0, color: 'var(--nf-warning)' }} />
                    <div>
                      <strong style={{ color: 'var(--nf-warning)' }}>ID Number Mismatch</strong>
                      <p style={{ fontSize: '0.82rem', marginTop: 3 }}>
                        {result.decision.id_mismatch?.reason
                          || result.explanation?.id_mismatch?.short_reason
                          || 'The ID number you entered does not match the uploaded document.'}
                      </p>
                      <p style={{ fontSize: '0.75rem', marginTop: 4, color: 'var(--nf-dim)' }}>
                        Entered: <strong>{result.decision.id_mismatch?.declared || result.explanation?.id_mismatch?.declared}</strong>
                        {' · '}
                        On document: <strong>{result.decision.id_mismatch?.extracted || result.explanation?.id_mismatch?.extracted}</strong>
                      </p>
                    </div>
                  </div>
                )}

                {(result.decision.name_mismatch?.detected || result.document_verdict?.name_mismatch || result.explanation?.name_mismatch) && (
                  <div className="nf-banner-rejected" style={{ borderColor: 'rgba(255,165,0,0.6)', background: 'rgba(255,165,0,0.08)' }}>
                    <AlertTriangle size={18} style={{ flexShrink: 0, color: 'var(--nf-warning)' }} />
                    <div>
                      <strong style={{ color: 'var(--nf-warning)' }}>Name Mismatch on Driving Licence</strong>
                      <p style={{ fontSize: '0.82rem', marginTop: 3 }}>
                        {result.decision.name_mismatch?.reason
                          || result.explanation?.name_mismatch?.short_reason
                          || 'The name you entered does not match the name on the driving licence.'}
                      </p>
                      <p style={{ fontSize: '0.75rem', marginTop: 4, color: 'var(--nf-dim)' }}>
                        Entered: <strong>{result.decision.name_mismatch?.declared || result.explanation?.name_mismatch?.declared}</strong>
                        {' · '}
                        On document: <strong>{result.decision.name_mismatch?.extracted || result.explanation?.name_mismatch?.extracted}</strong>
                      </p>
                    </div>
                  </div>
                )}

                {/* Document type mismatch — declared vs detected */}
                {result.document_verdict?.document_type_mismatch && (
                  <div className="nf-banner-rejected" style={{ borderColor: 'rgba(255,165,0,0.6)', background: 'rgba(255,165,0,0.08)' }}>
                    <AlertTriangle size={18} style={{ flexShrink: 0, color: 'var(--nf-warning)' }} />
                    <div>
                      <strong style={{ color: 'var(--nf-warning)' }}>
                        Document Type Mismatch
                        {result.document_verdict.mismatch_severity && result.document_verdict.mismatch_severity !== 'NONE' && (
                          <span style={{ fontSize: '0.65rem', marginLeft: 6, color: 'var(--nf-dim)' }}>
                            {result.document_verdict.mismatch_severity} severity
                          </span>
                        )}
                      </strong>
                      <p style={{ fontSize: '0.82rem', marginTop: 3 }}>
                        {result.document_verdict.doc_type_match?.reason
                          || 'Declared document type does not match the uploaded document.'}
                      </p>
                      <p style={{ fontSize: '0.75rem', marginTop: 4, color: 'var(--nf-dim)' }}>
                        Declared: <strong>{result.document_verdict.declared_doc_type || '—'}</strong>
                        {' · '}
                        Detected: <strong>{result.document_verdict.detected_doc_type || '—'}</strong>
                      </p>
                    </div>
                  </div>
                )}

                {/* Entered details vs document detail mismatch (DOB, nationality, …) */}
                {result.document_verdict?.field_verification?.has_mismatch && (
                  <div className="nf-banner-rejected" style={{ borderColor: 'rgba(255,165,0,0.6)', background: 'rgba(255,165,0,0.08)' }}>
                    <AlertTriangle size={18} style={{ flexShrink: 0, color: 'var(--nf-warning)' }} />
                    <div>
                      <strong style={{ color: 'var(--nf-warning)' }}>Entered Details Do Not Match the Document</strong>
                      <ul style={{ marginTop: 5, paddingLeft: '1rem', fontSize: '0.82rem' }}>
                        {result.document_verdict.field_verification.mismatches.map((m, i) => (
                          <li key={i}>
                            {m.label}: entered <strong>{m.declared}</strong> vs document <strong>{m.extracted}</strong>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}

                {/* Document Verdict Summary (non-rejected) */}
                {!result.document_rejected && result.document_verdict?.verdict && (
                  <div className={`nf-banner-verdict ${result.document_verdict.verdict.toLowerCase()}`}>
                    {result.document_verdict.verdict === 'VERIFIED'
                      ? <CheckCircle size={18} style={{ flexShrink: 0 }} />
                      : <AlertTriangle size={18} style={{ flexShrink: 0 }} />}
                    <div>
                      <strong>Document Verification: {result.document_verdict.verdict}</strong>
                      <p style={{ fontSize: '0.82rem', marginTop: 3 }}>{result.document_verdict.summary}</p>
                    </div>
                  </div>
                )}
                <div className="nf-card">
                  <div className="nf-tabs">
                    {(['overview', 'pipeline', 'documents', 'evidence', 'audit', 'copilot'] as Tab[]).map((t) => (
                      <button key={t} className={`nf-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                        {t === 'documents' ? '🪪 Documents' : t === 'copilot' ? '💬 Copilot' : t.charAt(0).toUpperCase() + t.slice(1)}
                      </button>
                    ))}
                  </div>

                  {tab === 'overview' && (
                    <>
                      <h3>Customer Profile</h3>
                      <div className="nf-profile-grid" style={{ marginBottom: '1.5rem' }}>
                        {PROFILE_KEYS.map((key) => {
                          const fs = fieldStatus?.[key]
                          const rawVal = result.customer_profile[key] || ''
                          // Show the full country name; other fields unchanged.
                          const val = key === 'nationality' ? countryLabel(rawVal) : rawVal
                          const missing = fs?.status === 'missing' || (!rawVal && key !== 'intake_confidence')
                          return (
                            <div key={key} className={`nf-profile-field ${missing ? (fs?.required ? 'missing-required' : 'missing-optional') : ''}`}>
                              <label>{PROFILE_LABELS[key] || fs?.label || key.replace(/_/g, ' ')}</label>
                              <span className={missing ? 'missing-value' : ''}>{val || '—'}</span>
                            </div>
                          )
                        })}
                      </div>

                      {result.uploaded_evidence?.length > 0 && (
                        <>
                          <h3>Uploaded Documents</h3>
                          <div className="nf-doc-grid" style={{ marginBottom: '1.5rem' }}>
                            {result.uploaded_evidence.map((d) => (
                              <div key={d.evidence_id} className="nf-doc-item">
                                <CheckCircle size={16} style={{ color: 'var(--nf-success)' }} />
                                <span>{d.original_filename}</span>
                              </div>
                            ))}
                          </div>
                        </>
                      )}

                      <h3>Risk Breakdown</h3>
                      {result.risk_assessment.breakdown.map((b, i) => (
                        <div key={i} className={`nf-breakdown-item ${b.source === 'ml' ? 'nf-breakdown-ml' : ''}`}>
                          <span>{b.signal}</span>
                          <span className="pts">+{b.points}</span>
                        </div>
                      ))}

                      {result.risk_assessment.scoring_method && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--nf-dim)' }}>
                          <span>Scoring method:</span>
                          <span style={{ color: result.risk_assessment.scoring_method === 'hybrid' ? 'var(--nf-success)' : 'var(--nf-muted)', fontWeight: 600 }}>
                            {result.risk_assessment.scoring_method === 'hybrid' ? '⚡ Hybrid (XGBoost + Rules)' : '📋 Rule-based'}
                          </span>
                          {result.risk_assessment.rule_score !== undefined && (
                            <span>| Rule: {result.risk_assessment.rule_score} · ML: {result.risk_assessment.ml_result?.ml_risk_score ?? '—'}</span>
                          )}
                        </div>
                      )}

                      {result.risk_assessment.ml_result?.ml_used && (
                        <div className="nf-ml-badge">
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                            <span style={{ fontWeight: 700, fontSize: '0.75rem' }}>🤖 XGBoost Prediction</span>
                            <span style={{ fontSize: '0.7rem', color: 'var(--nf-dim)' }}>
                              {Math.round(result.risk_assessment.ml_result.ml_confidence * 100)}% confidence
                            </span>
                          </div>
                          <div style={{ display: 'flex', gap: '0.5rem' }}>
                            {(['Low', 'Medium', 'High'] as const).map((level) => {
                              const p = result.risk_assessment.ml_result!.ml_probabilities[level]
                              const isMax = level === result.risk_assessment.ml_result!.ml_risk_level
                              return (
                                <div key={level} style={{ flex: 1, textAlign: 'center', padding: '0.4rem', borderRadius: 4, background: isMax ? 'rgba(229,9,20,0.15)' : 'rgba(255,255,255,0.04)', border: isMax ? '1px solid rgba(229,9,20,0.4)' : '1px solid rgba(255,255,255,0.06)' }}>
                                  <div style={{ fontSize: '0.65rem', color: 'var(--nf-dim)' }}>{level}</div>
                                  <div style={{ fontWeight: 700, fontSize: '0.85rem', color: isMax ? 'var(--nf-red)' : 'var(--nf-muted)' }}>{Math.round(p * 100)}%</div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )}

                      {/* Verification Confidence Breakdown (Part 6) */}
                      {result.agent_confidences && Object.keys(result.agent_confidences).length > 0 && (
                        <>
                          <h3 style={{ marginTop: '1.5rem' }}>Verification Confidence Breakdown</h3>
                          {AGENT_CONFIDENCE_ORDER
                            .filter((key) => hasConfidence(result.agent_confidences?.[key]))
                            .map((key) => {
                              const val = result.agent_confidences![key]
                              return (
                                <div key={key} style={{ margin: '0.5rem 0' }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: 3 }}>
                                    <span>{AGENT_CONFIDENCE_LABELS[key] || key}</span>
                                    <span style={{ color: 'var(--nf-muted)' }}>{confidencePct(val)}%</span>
                                  </div>
                                  <div className="nf-score-bar">
                                    <div className="nf-score-fill" style={{ width: `${confidencePct(val)}%` }} />
                                  </div>
                                </div>
                              )
                            })}
                        </>
                      )}

                      {/* Risk Contribution Breakdown (Parts 5 & 6) — bars, descending */}
                      {(result.risk_contributions?.length ?? 0) > 0 && (() => {
                        const contribs = result.risk_contributions!
                        const max = maxAbsImpact(contribs)
                        return (
                          <>
                            <h3 style={{ marginTop: '1.5rem' }}>Risk Contribution Breakdown</h3>
                            {contribs.map((c, i) => (
                              <div key={i} style={{ margin: '0.5rem 0' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: 3 }}>
                                  <span>{c.factor}</span>
                                  <span className="pts" style={{ color: c.impact >= 0 ? 'var(--nf-red)' : 'var(--nf-success)' }}>
                                    {formatImpact(c.impact)}
                                  </span>
                                </div>
                                <div className="nf-score-bar">
                                  <div
                                    className="nf-score-fill"
                                    style={{ width: `${impactBarWidth(c.impact, max)}%`, background: c.impact >= 0 ? 'var(--nf-red)' : 'var(--nf-success)' }}
                                  />
                                </div>
                              </div>
                            ))}
                          </>
                        )
                      })()}

                      <div className="nf-narrative" style={{ marginTop: '1rem' }}>{result.explanation.narrative}</div>

                      {/* ── Escalation Reasons — Groq one-liners (ESCALATE / REVIEW) ── */}
                      {(result.decision.status === 'ESCALATE' || result.decision.status === 'REVIEW') && (() => {
                        const groqReasons = (result.decision.reasons || result.explanation?.reasons || [])
                          .filter((r: string) => r && !r.startsWith('Document verification failed'))

                        const reasons: { label: string; detail: string; severity: 'high' | 'medium' }[] = []

                        // Document rejection (hard failures)
                        if (result.document_rejected && result.document_verdict?.rejection_reasons?.length) {
                          result.document_verdict.rejection_reasons
                            .filter((r: string) => !r.startsWith('  └'))
                            .forEach((r: string) => reasons.push({ label: 'Document', detail: r, severity: 'high' }))
                        }

                        // Groq one-liner reasons (primary source)
                        groqReasons.forEach((r: string) => {
                          const lower = r.toLowerCase()
                          reasons.push({
                            label: result.decision.groq_powered ? 'Groq AI' : 'Risk Signal',
                            detail: r,
                            severity: lower.includes('sanctions') || lower.includes('pep') || lower.includes('mismatch') || lower.includes('document') ? 'high' : 'medium',
                          })
                        })

                        // Fallback breakdown only when Groq reasons unavailable
                        if (!groqReasons.length && result.risk_assessment?.breakdown?.length && !result.document_rejected) {
                          result.risk_assessment.breakdown
                            .filter(b => b.source !== 'ml' && b.points >= 10)
                            .forEach(b => {
                              reasons.push({
                                label: 'Risk Factor',
                                detail: b.signal,
                                severity: b.points >= 25 ? 'high' : 'medium',
                              })
                            })
                        }

                        if (reasons.length === 0) return null

                        return (
                          <div className="nf-escalation-block">
                            <div className="nf-escalation-header">
                              <XCircle size={16} style={{ color: result.decision.status === 'ESCALATE' ? 'var(--nf-red)' : 'var(--nf-warning)', flexShrink: 0 }} />
                              <span>
                                {result.decision.status === 'ESCALATE' ? 'Escalation Reasons' : 'Review Reasons'}
                                {result.decision.groq_powered && <span style={{ fontSize: '0.65rem', marginLeft: 6, color: 'var(--nf-dim)' }}>via Groq</span>}
                                <span className="nf-escalation-count">{reasons.length}</span>
                              </span>
                            </div>
                            <div className="nf-escalation-list">
                              {reasons.map((r, i) => (
                                <div key={i} className={`nf-escalation-item ${r.severity}`}>
                                  <div className="nf-escalation-detail" style={{ fontSize: '0.9rem' }}>{r.detail}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )
                      })()}
                    </>
                  )}

                  {tab === 'pipeline' && (
                    <div className="nf-timeline">
                      {result.audit_log.map((e, i) => (
                        <div key={i} className="nf-timeline-item">
                          <div className="nf-timeline-dot" />
                          <div>
                            <div className="nf-timeline-agent">{e.agent}</div>
                            <div className="nf-timeline-action">{e.action}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {tab === 'documents' && (
                    <div>
                      <h3>Indian KYC Document Verification</h3>
                      <p style={{ fontSize: '0.82rem', color: 'var(--nf-muted)', margin: '0.5rem 0 1.25rem' }}>
                        XGBoost ML — classifies and validates Indian proof documents per RBI KYC Master Directions
                      </p>

                      {result.document_verdict ? (
                        <>
                          {/* Declared vs Detected document type */}
                          {(result.document_verdict.declared_doc_type || result.document_verdict.detected_doc_type) && (
                            <div className={`nf-doctype-check ${result.document_verdict.document_type_mismatch ? 'mismatch' : 'match'}`}>
                              <div className="nf-doctype-row">
                                <div>
                                  <div className="nf-doctype-label">Declared Type</div>
                                  <div className="nf-doctype-value">{result.document_verdict.declared_doc_type || '—'}</div>
                                </div>
                                <div>
                                  <div className="nf-doctype-label">Detected Type</div>
                                  <div className="nf-doctype-value">{result.document_verdict.detected_doc_type || '—'}</div>
                                </div>
                              </div>
                              <div className="nf-doctype-status">
                                {result.document_verdict.document_type_mismatch
                                  ? <><AlertTriangle size={14} /> Document Type Mismatch</>
                                  : <><CheckCircle size={14} /> Document Type Verified</>}
                              </div>
                            </div>
                          )}

                          {/* Detail verification — entered vs document (name, DOB, ID, nationality) */}
                          {(result.document_verdict.field_verification?.checks?.length ?? 0) > 0 && (
                            <div className={`nf-detailcheck ${result.document_verdict.field_verification!.has_mismatch ? 'mismatch' : 'match'}`}>
                              <div className="nf-detailcheck-title">
                                {result.document_verdict.field_verification!.has_mismatch
                                  ? <><AlertTriangle size={14} /> Entered details do not match the document</>
                                  : <><CheckCircle size={14} /> Entered details match the document</>}
                              </div>
                              <div className="nf-detailcheck-rows">
                                {result.document_verdict.field_verification!.checks.map((c, i) => (
                                  <div key={i} className={`nf-detailcheck-row ${c.match ? 'ok' : 'bad'}`}>
                                    <span className="nf-detailcheck-field">{c.label}</span>
                                    <span className="nf-detailcheck-vals">
                                      <span>Entered: <strong>{c.declared}</strong></span>
                                      <span>Document: <strong>{c.extracted}</strong></span>
                                    </span>
                                    <span className="nf-detailcheck-mark">{c.match ? '✓' : '✗'}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Summary stats */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: '0.5rem', marginBottom: '1.25rem' }}>
                            {[
                              { label: 'Total Docs', value: result.document_verdict.total_docs, color: 'var(--nf-text)' },
                              { label: 'Verified', value: result.document_verdict.verified_count, color: 'var(--nf-success)' },
                              { label: 'Rejected', value: result.document_verdict.rejected_count, color: 'var(--nf-red)' },
                              { label: 'Review', value: result.document_verdict.review_count, color: 'var(--nf-warning)' },
                            ].map((s, i) => (
                              <div key={i} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 6, padding: '0.6rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.6rem', color: 'var(--nf-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{s.label}</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: s.color }}>{s.value}</div>
                              </div>
                            ))}
                          </div>

                          {/* POI / POA badges */}
                          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                            <span className={`nf-doc-badge ${result.document_verdict.has_poi ? 'valid' : 'invalid'}`}>
                              {result.document_verdict.has_poi ? '✓' : '✗'} Proof of Identity
                            </span>
                            <span className={`nf-doc-badge ${result.document_verdict.has_poa ? 'valid' : 'invalid'}`}>
                              {result.document_verdict.has_poa ? '✓' : '✗'} Proof of Address
                            </span>
                          </div>

                          {/* Per-document cards */}
                          {result.document_verdict.per_document?.map((doc, i) => (
                            <div key={i} className={`nf-verdict-doc-card ${doc.verdict.toLowerCase()}`}>
                              <div className="nf-verdict-header">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                  <span className="nf-verdict-type">{doc.doc_type_display}</span>
                                  <span style={{ fontSize: '0.65rem', color: 'var(--nf-dim)' }}>
                                    {Math.round(doc.doc_type_confidence * 100)}% match
                                  </span>
                                </div>
                                <span className={`nf-verdict-pill ${doc.verdict.toLowerCase()}`}>
                                  {doc.verdict === 'VERIFIED' ? '✓ ' : doc.verdict === 'REJECTED' ? '✗ ' : '⚠ '}
                                  {doc.verdict}
                                  <span style={{ opacity: 0.7, marginLeft: 4, fontSize: '0.65rem' }}>
                                    ({Math.round(doc.validity_confidence * 100)}%)
                                  </span>
                                </span>
                              </div>

                              <div style={{ fontSize: '0.72rem', color: 'var(--nf-dim)', marginBottom: '0.25rem' }}>
                                📄 {doc.filename}
                                {doc.doc_number && (
                                  <span style={{ marginLeft: '0.6rem', color: 'var(--nf-muted)', fontFamily: 'monospace' }}>
                                    #{doc.doc_number}
                                  </span>
                                )}
                              </div>

                              <div className="nf-verdict-reason">{doc.verdict_reason}</div>

                              {/* KYC purpose tags */}
                              <div style={{ display: 'flex', gap: '0.35rem', margin: '0.4rem 0' }}>
                                <span style={{ fontSize: '0.62rem', padding: '0.1rem 0.4rem', borderRadius: 3, background: doc.kyc_purpose?.poi ? 'rgba(70,211,105,0.12)' : 'rgba(255,255,255,0.04)', color: doc.kyc_purpose?.poi ? 'var(--nf-success)' : 'var(--nf-dim)', border: '1px solid currentColor' }}>POI</span>
                                <span style={{ fontSize: '0.62rem', padding: '0.1rem 0.4rem', borderRadius: 3, background: doc.kyc_purpose?.poa ? 'rgba(70,211,105,0.12)' : 'rgba(255,255,255,0.04)', color: doc.kyc_purpose?.poa ? 'var(--nf-success)' : 'var(--nf-dim)', border: '1px solid currentColor' }}>POA</span>
                                <span style={{ fontSize: '0.62rem', padding: '0.1rem 0.4rem', borderRadius: 3, background: 'rgba(255,255,255,0.04)', color: 'var(--nf-dim)', border: '1px solid rgba(255,255,255,0.1)' }}>
                                  {Math.round(doc.completeness_score * 100)}% complete
                                </span>
                                <span style={{ fontSize: '0.62rem', padding: '0.1rem 0.4rem', borderRadius: 3, background: 'rgba(255,255,255,0.04)', color: 'var(--nf-dim)', border: '1px solid rgba(255,255,255,0.1)' }}>
                                  {Math.round(doc.trust_signal_score * 100)}% trust
                                </span>
                              </div>

                              {/* Validity issues */}
                              {doc.validity_issues?.length > 0 && (
                                <div style={{ marginTop: '0.35rem' }}>
                                  {doc.validity_issues.map((issue, j) => (
                                    <div key={j} className="nf-verdict-issue">
                                      <AlertTriangle size={10} style={{ flexShrink: 0, marginTop: 2 }} />
                                      {issue}
                                    </div>
                                  ))}
                                </div>
                              )}

                              {/* Groq extracted fields */}
                              {doc.groq_extracted_fields && Object.keys(doc.groq_extracted_fields).length > 0 && (
                                <details className="nf-groq-fields" style={{ marginTop: '0.75rem' }}>
                                  <summary style={{ cursor: 'pointer', fontSize: '0.7rem', color: 'var(--nf-dim)', userSelect: 'none', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                    <span style={{ color: 'var(--nf-red)', fontSize: '0.65rem' }}>✦</span> Groq Extracted Fields
                                  </summary>
                                  <div className="nf-groq-fields-grid">
                                    {Object.entries(doc.groq_extracted_fields).map(([key, val]) => (
                                      <div key={key} className="nf-groq-field-row">
                                        <span className="nf-groq-field-key">{key.replace(/_/g, ' ')}</span>
                                        <span className="nf-groq-field-val">
                                          {typeof val === 'boolean' ? (val ? '✓ Yes' : '✗ No') : String(val)}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                  {doc.groq_notes && (
                                    <div style={{ fontSize: '0.72rem', color: 'var(--nf-muted)', marginTop: '0.5rem', fontStyle: 'italic', paddingLeft: '0.5rem', borderLeft: '2px solid rgba(229,9,20,0.3)' }}>
                                      {doc.groq_notes}
                                    </div>
                                  )}
                                  {doc.groq_integrity_score !== undefined && doc.groq_integrity_score !== null && (
                                    <div style={{ fontSize: '0.7rem', color: 'var(--nf-dim)', marginTop: '0.4rem' }}>
                                      Groq integrity score: <strong style={{ color: doc.groq_integrity_score >= 0.7 ? 'var(--nf-success)' : 'var(--nf-warning)' }}>{Math.round(doc.groq_integrity_score * 100)}%</strong>
                                    </div>
                                  )}
                                </details>
                              )}

                              {/* QR Fallback Panel */}
                              {(doc as any).qr_scan_result && (
                                <div className={`nf-qr-panel ${(doc as any).qr_fallback_used ? 'success' : (doc as any).qr_scan_result?.qr_found ? 'warning' : 'inactive'}`}>
                                  <div className="nf-qr-header">
                                    <span className="nf-qr-icon">
                                      {(doc as any).qr_fallback_used ? '✓' : (doc as any).qr_scan_result?.qr_found ? '⚠' : '—'}
                                    </span>
                                    <span className="nf-qr-title">
                                      QR / Barcode Fallback
                                      {(doc as any).qr_fallback_used && <span className="nf-qr-badge">NUMBER RECOVERED</span>}
                                    </span>
                                    <span style={{ fontSize: '0.65rem', color: 'var(--nf-dim)', marginLeft: 'auto' }}>
                                      {(doc as any).qr_scan_result?.qr_type || '—'}
                                    </span>
                                  </div>

                                  {(doc as any).qr_fallback_note && (
                                    <p className="nf-qr-note">{(doc as any).qr_fallback_note}</p>
                                  )}

                                  {(doc as any).qr_scan_result?.qr_found && (
                                    <div className="nf-qr-detail-row">
                                      <span>QR doc number</span>
                                      <span style={{ fontFamily: 'monospace', color: 'var(--nf-text)' }}>
                                        {(doc as any).qr_scan_result?.qr_document_number || '—'}
                                      </span>
                                    </div>
                                  )}

                                  {(doc as any).qr_scan_result?.scan_confidence !== undefined && (
                                    <div className="nf-qr-detail-row">
                                      <span>Scan confidence</span>
                                      <span>{Math.round(((doc as any).qr_scan_result?.scan_confidence ?? 0) * 100)}%</span>
                                    </div>
                                  )}

                                  {/* Cross-match result */}
                                  {(doc as any).qr_cross_match_result && (
                                    <>
                                      <div className="nf-qr-divider" />
                                      <div className="nf-qr-detail-row">
                                        <span>Cross-match score</span>
                                        <strong style={{ color: ((doc as any).qr_cross_match_result?.match_score ?? 0) >= 0.7 ? 'var(--nf-success)' : 'var(--nf-warning)' }}>
                                          {Math.round(((doc as any).qr_cross_match_result?.match_score ?? 0) * 100)}%
                                        </strong>
                                      </div>
                                      <div className="nf-qr-detail-row">
                                        <span>Integrity verdict</span>
                                        <span className={`nf-qr-integrity ${(doc as any).qr_cross_match_result?.integrity_verdict}`}>
                                          {(doc as any).qr_cross_match_result?.integrity_verdict?.replace(/_/g, ' ') || '—'}
                                        </span>
                                      </div>
                                      {((doc as any).qr_cross_match_result?.matched_fields?.length ?? 0) > 0 && (
                                        <div className="nf-qr-detail-row">
                                          <span>Matched fields</span>
                                          <span style={{ color: 'var(--nf-success)', fontSize: '0.7rem' }}>
                                            {(doc as any).qr_cross_match_result?.matched_fields?.join(', ')}
                                          </span>
                                        </div>
                                      )}
                                      {((doc as any).qr_cross_match_result?.mismatched_fields?.length ?? 0) > 0 && (
                                        <div style={{ marginTop: '0.3rem' }}>
                                          {((doc as any).qr_cross_match_result?.mismatched_fields ?? []).map((m: any, k: number) => (
                                            <div key={k} className="nf-qr-mismatch">
                                              <AlertTriangle size={9} />
                                              <span><strong>{m.field}</strong>: text="{m.text_value}" vs qr="{m.qr_value}"
                                                {m.severity === 'critical' && <span className="nf-qr-critical"> CRITICAL</span>}
                                              </span>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}

                          {result.document_verdict.per_document?.length === 0 && (
                            <div style={{ textAlign: 'center', color: 'var(--nf-dim)', padding: '2rem', fontSize: '0.9rem' }}>
                              No documents were uploaded for this case.
                            </div>
                          )}
                        </>
                      ) : (
                        <div style={{ color: 'var(--nf-dim)', fontSize: '0.9rem' }}>No document verification data available.</div>
                      )}
                    </div>
                  )}

                  {tab === 'evidence' && (
                    <div>
                      {/* Prefer document_verdict (from Indian Doc Verification Agent)
                          over evidence_validation.ml_classification (which may be stale) */}
                      {(() => {
                        // Use document_verdict if available (new pipeline), else fall back to ml_classification
                        const dvPerDoc = result.document_verdict?.per_document
                        const mlPerDoc = result.evidence_validation?.ml_classification?.per_document
                        const perDoc   = (dvPerDoc && dvPerDoc.length > 0) ? dvPerDoc : mlPerDoc
                        const hasPoi   = result.document_verdict?.has_poi ?? result.evidence_validation?.has_proof_of_identity ?? false
                        const hasPoa   = result.document_verdict?.has_poa ?? result.evidence_validation?.has_proof_of_address ?? false
                        const mlUsed   = !!(perDoc && perDoc.length > 0)

                        // Normalise per_document entries from either source to a common shape
                        const normDoc = (doc: any) => ({
                          evidence_id:         doc.evidence_id,
                          filename:            doc.filename,
                          doc_type:            doc.doc_type,
                          doc_type_display:    doc.doc_type_display || (doc.doc_type || '').replace(/_/g,' ').replace(/\b\w/g,(c:string)=>c.toUpperCase()),
                          doc_type_confidence: doc.doc_type_confidence ?? 0,
                          // document_verdict uses "verdict" field; ml_classification uses "is_valid"
                          is_valid:            doc.verdict === 'VERIFIED' || doc.is_valid === true,
                          validity_confidence: doc.validity_confidence ?? 0,
                          validity_issues:     doc.validity_issues ?? [],
                          doc_number:          doc.doc_number ?? '',
                          kyc_purpose:         doc.kyc_purpose ?? { poi: false, poa: false },
                          completeness_score:  doc.completeness_score ?? 0,
                          trust_signal_score:  doc.trust_signal_score ?? 0,
                          groq_extracted_fields: doc.groq_extracted_fields ?? {},
                          groq_notes:          doc.groq_notes ?? '',
                          groq_integrity_score: doc.groq_integrity_score,
                          // Verdict badge text
                          verdict_label: doc.verdict || (doc.is_valid ? 'VERIFIED' : 'INVALID'),
                        })

                        if (!mlUsed) return null

                        return (
                          <div style={{ marginBottom: '1.5rem' }}>
                            <h3>🤖 Indian KYC Document Verification (ML + Vision)</h3>
                            <p style={{ fontSize: '0.82rem', color: 'var(--nf-muted)', margin: '0.5rem 0 1rem' }}>
                              Groq Vision + HuggingFace OpenCV QR + XGBoost · Aadhaar · PAN · Passport · Voter ID · Driving Licence
                            </p>

                            {/* POI / POA badges */}
                            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
                              <span className={`nf-doc-badge ${hasPoi ? 'valid' : 'invalid'}`}>
                                {hasPoi ? '✓' : '✗'} Proof of Identity
                              </span>
                              <span className={`nf-doc-badge ${hasPoa ? 'valid' : 'invalid'}`}>
                                {hasPoa ? '✓' : '✗'} Proof of Address
                              </span>
                            </div>

                            {/* Per-document results */}
                            {perDoc!.map((rawDoc: any, i: number) => {
                              const doc = normDoc(rawDoc)
                              return (
                                <div key={i} className={`nf-doc-classification ${doc.is_valid ? 'valid' : 'invalid'}`}>
                                  <div className="nf-doc-cls-header">
                                    <div>
                                      <span className="nf-doc-type-badge">{doc.doc_type_display}</span>
                                      <span style={{ fontSize: '0.7rem', color: 'var(--nf-dim)', marginLeft: '0.5rem' }}>
                                        {Math.round(doc.doc_type_confidence * 100)}% confident
                                      </span>
                                    </div>
                                    <span className={`nf-validity-badge ${doc.is_valid ? 'valid' : 'invalid'}`}>
                                      {doc.is_valid ? '✓ ' : '✗ '}{doc.verdict_label}
                                      <span style={{ fontSize: '0.65rem', marginLeft: 4 }}>
                                        ({Math.round(doc.validity_confidence * 100)}%)
                                      </span>
                                    </span>
                                  </div>

                                  <div style={{ fontSize: '0.75rem', color: 'var(--nf-dim)', margin: '0.35rem 0' }}>
                                    📄 {doc.filename}
                                    {doc.doc_number && <span style={{ marginLeft: '0.75rem', color: 'var(--nf-muted)' }}>#{doc.doc_number}</span>}
                                  </div>

                                  {/* Completeness + Trust bars */}
                                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', margin: '0.5rem 0' }}>
                                    <div>
                                      <div style={{ fontSize: '0.6rem', color: 'var(--nf-dim)', marginBottom: 2 }}>Completeness</div>
                                      <div className="nf-score-bar"><div className="nf-score-fill" style={{ width: `${Math.round(doc.completeness_score * 100)}%` }} /></div>
                                      <div style={{ fontSize: '0.65rem', color: 'var(--nf-muted)', marginTop: 2 }}>{Math.round(doc.completeness_score * 100)}%</div>
                                    </div>
                                    <div>
                                      <div style={{ fontSize: '0.6rem', color: 'var(--nf-dim)', marginBottom: 2 }}>Trust Signal</div>
                                      <div className="nf-score-bar"><div className="nf-score-fill trust" style={{ width: `${Math.round(doc.trust_signal_score * 100)}%` }} /></div>
                                      <div style={{ fontSize: '0.65rem', color: 'var(--nf-muted)', marginTop: 2 }}>{Math.round(doc.trust_signal_score * 100)}%</div>
                                    </div>
                                  </div>

                                  {/* KYC Purpose */}
                                  <div style={{ display: 'flex', gap: '0.35rem', marginBottom: '0.4rem' }}>
                                    <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem', borderRadius: 3, background: doc.kyc_purpose?.poi ? 'rgba(70,211,105,0.15)' : 'rgba(255,255,255,0.04)', color: doc.kyc_purpose?.poi ? 'var(--nf-success)' : 'var(--nf-dim)', border: '1px solid currentColor' }}>POI</span>
                                    <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem', borderRadius: 3, background: doc.kyc_purpose?.poa ? 'rgba(70,211,105,0.15)' : 'rgba(255,255,255,0.04)', color: doc.kyc_purpose?.poa ? 'var(--nf-success)' : 'var(--nf-dim)', border: '1px solid currentColor' }}>POA</span>
                                  </div>

                                  {/* Validity Issues */}
                                  {doc.validity_issues?.length > 0 && (
                                    <div style={{ marginTop: '0.4rem' }}>
                                      {doc.validity_issues.map((issue: string, j: number) => (
                                        <div key={j} className="nf-doc-issue">
                                          <AlertTriangle size={11} /> {issue}
                                        </div>
                                      ))}
                                    </div>
                                  )}

                                  {/* Groq extracted fields */}
                                  {doc.groq_extracted_fields && Object.keys(doc.groq_extracted_fields).length > 0 && (
                                    <details className="nf-groq-fields" style={{ marginTop: '0.75rem' }}>
                                      <summary style={{ cursor: 'pointer', fontSize: '0.7rem', color: 'var(--nf-dim)', userSelect: 'none', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                        <span style={{ color: 'var(--nf-red)', fontSize: '0.65rem' }}>✦</span> Groq Extracted Fields
                                      </summary>
                                      <div className="nf-groq-fields-grid">
                                        {Object.entries(doc.groq_extracted_fields).map(([key, val]) => (
                                          <div key={key} className="nf-groq-field-row">
                                            <span className="nf-groq-field-key">{key.replace(/_/g, ' ')}</span>
                                            <span className="nf-groq-field-val">{typeof val === 'boolean' ? (val ? '✓ Yes' : '✗ No') : String(val)}</span>
                                          </div>
                                        ))}
                                      </div>
                                      {doc.groq_notes && (
                                        <div style={{ fontSize: '0.72rem', color: 'var(--nf-muted)', marginTop: '0.5rem', fontStyle: 'italic', paddingLeft: '0.5rem', borderLeft: '2px solid rgba(229,9,20,0.3)' }}>
                                          {doc.groq_notes}
                                        </div>
                                      )}
                                      {doc.groq_integrity_score != null && (
                                        <div style={{ fontSize: '0.7rem', color: 'var(--nf-dim)', marginTop: '0.4rem' }}>
                                          Groq integrity: <strong style={{ color: doc.groq_integrity_score >= 0.7 ? 'var(--nf-success)' : 'var(--nf-warning)' }}>{Math.round(doc.groq_integrity_score * 100)}%</strong>
                                        </div>
                                      )}
                                    </details>
                                  )}
                                </div>
                              )
                            })}

                            {/* Aggregate stats */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: '0.5rem', marginTop: '0.75rem' }}>
                            {[
                              { label: 'Docs Valid', value: `${perDoc!.filter((d:any) => d.verdict === 'VERIFIED' || d.is_valid === true).length}/${perDoc!.length}` },
                              { label: 'Avg Completeness', value: `${Math.round((perDoc!.reduce((s:number,d:any) => s + (d.completeness_score ?? 0), 0) / Math.max(perDoc!.length, 1)) * 100)}%` },
                              { label: 'Avg Trust', value: `${Math.round((perDoc!.reduce((s:number,d:any) => s + (d.trust_signal_score ?? 0), 0) / Math.max(perDoc!.length, 1)) * 100)}%` },
                            ].map((s, i) => (
                              <div key={i} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 6, padding: '0.5rem', textAlign: 'center' }}>
                                <div style={{ fontSize: '0.65rem', color: 'var(--nf-dim)', marginBottom: 2 }}>{s.label}</div>
                                <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{s.value}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                        )
                      })()} 

                      {result.evidence_validation?.summary && (
                        <div style={{ marginBottom: '1.5rem' }}>
                          <h3>Groq Document Validation</h3>
                          <p style={{ fontSize: '0.9rem', color: 'var(--nf-muted)', margin: '0.5rem 0 1rem' }}>
                            {String(result.evidence_validation.summary)}
                          </p>
                          <div className="nf-breakdown-item">
                            <span>Identity Verified</span>
                            <span>{result.evidence_validation.identity_verified ? '✓' : '✗'}</span>
                          </div>
                          <div className="nf-breakdown-item">
                            <span>ML Validation</span>
                            <span>{result.evidence_validation.ml_validation_passed ? '✓ Passed' : '✗ Failed'}</span>
                          </div>
                          <div className="nf-breakdown-item">
                            <span>Groq Validation</span>
                            <span>{result.evidence_validation.groq_validation_passed ? '✓ Passed' : '✗ Failed'}</span>
                          </div>
                          <div className="nf-breakdown-item">
                            <span>Combined Validation</span>
                            <span>{result.evidence_validation.validation_passed ? '✓ Passed' : '✗ Failed'}</span>
                          </div>
                        </div>
                      )}

                      {Boolean(result.groq_verification?.summary) && (
                        <div>
                          <h3>Groq Profile Check</h3>
                          <p style={{ fontSize: '0.9rem', color: 'var(--nf-muted)', marginTop: '0.5rem' }}>
                            {String(result.groq_verification.summary)}
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {tab === 'audit' && result.decision.audit_report && (
                    <pre style={{ fontSize: '0.72rem', color: 'var(--nf-muted)', overflow: 'auto', maxHeight: 400, whiteSpace: 'pre-wrap' }}>
                      {JSON.stringify(result.decision.audit_report, null, 2)}
                    </pre>
                  )}

                  {tab === 'copilot' && (
                    <CopilotPanel caseId={result.case_id} result={result} />
                  )}
                </div>

                {result.decision.requires_human_review && !result.decision.human_reviewed && (
                  <HumanReviewPanel
                    caseId={result.case_id}
                    briefing={String((result.human_review?.groq_officer_briefing as Record<string, string> | undefined)?.summary || '') || undefined}
                    confidence={result.overall_confidence}
                    topRiskDrivers={result.top_risk_drivers}
                    eddSummary={result.edd_triggered ? result.edd_summary : undefined}
                    consistencyIssues={result.consistency_issues}
                    recommendation={result.decision.review_recommendation}
                    onAskCopilot={() => setTab('copilot')}
                    onComplete={handleReview}
                  />
                )}
              </>
            )}
          </div>
        </div>
      </main>
            </>
          }
        />
      </Routes>
    </>
  )
}
