import { ReactNode, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  CheckCircle,
  AlertTriangle,
  XCircle,
  User,
  Shield,
  Sparkles,
} from 'lucide-react'
import { FieldStatus, KYCResult, fetchCase } from '../api'
import ErrorBoundary from '../components/ErrorBoundary'
import HumanReviewPanel from '../components/HumanReviewPanel'
import EvidenceDetailSection from '../components/EvidenceDetailSection'
import { decisionClass, decisionLabel } from '../utils/decision'
import { collectReasons, getProfileStatus, getStatusSummary } from '../utils/profileReasons'
import { countryLabel } from '../country'
import {
  confidenceBand,
  confidenceIcon,
  confidenceLabel,
  confidencePct,
  hasConfidence,
} from '../utils/confidence'
import {
  consistencyBand,
  consistencyIcon,
  consistencyLabel,
  consistencyPct,
  sortBySeverity,
} from '../utils/consistency'

const PROFILE_KEYS = ['name', 'dob', 'nationality', 'occupation', 'source_of_funds', 'document_type', 'id_number']

// Display labels for profile fields when the backend field_status label is absent.
const PROFILE_LABELS: Record<string, string> = {
  nationality: 'Country',
  document_type: 'Document Type',
  id_number: 'Document Number',
}

function DecisionIcon({ status }: { status: string }) {
  if (status === 'APPROVE') return <CheckCircle size={36} />
  if (status === 'REVIEW') return <AlertTriangle size={36} />
  return <XCircle size={36} />
}

function ProfileShell({
  caseId,
  title,
  statusClass = '',
  children,
}: {
  caseId?: string
  title: string
  statusClass?: string
  children: ReactNode
}) {
  return (
    <>
      <section className={`nf-hero nf-hero-compact nf-profile-detail-hero ${statusClass}`}>
        <div className="nf-hero-content">
          <Link to="/profiles" className="nf-profile-back">
            <ArrowLeft size={16} />
            Back to Profiles
          </Link>
          <h1>{title}</h1>
          {caseId && <p className="nf-profile-detail-id">{caseId}</p>}
        </div>
      </section>
      <main className="nf-main nf-profile-detail nf-profile-detail-body">
        {children}
      </main>
    </>
  )
}

function ProfileDetailContent({
  result,
  onReviewComplete,
}: {
  result: KYCResult
  onReviewComplete: (updated: KYCResult) => void
}) {
  const status = getProfileStatus(result)
  const dc = decisionClass(status)
  const decision = result.decision ?? {}
  const risk = result.risk_assessment ?? { risk_score: 0, risk_level: 'Unknown', breakdown: [] }
  const breakdown = risk.breakdown ?? []
  const customerProfile = result.customer_profile ?? {}
  const displayStatus = decision.final_status || decision.status || 'PENDING'
  const fieldStatus = result.field_status || result.document_extraction?.field_status as Record<string, FieldStatus> | undefined
  const reasons = collectReasons(result)
  const summary = getStatusSummary(status, result)
  const pendingReview = Boolean(decision.requires_human_review && !decision.human_reviewed)
  const officerBriefing = (result.human_review?.groq_officer_briefing as Record<string, string> | undefined)?.summary

  return (
    <>
      {pendingReview && (
        <HumanReviewPanel
          caseId={result.case_id}
          briefing={officerBriefing}
          confidence={result.overall_confidence}
          topRiskDrivers={result.top_risk_drivers}
          eddSummary={result.edd_triggered ? result.edd_summary : undefined}
          consistencyIssues={result.consistency_issues}
          onComplete={onReviewComplete}
        />
      )}

      <div className={`nf-decision-hero ${dc}`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <DecisionIcon status={status} />
          <div>
            <div className="nf-decision-label">Status</div>
            <div className="nf-decision-value">{decisionLabel(status)}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--nf-dim)', marginTop: 4 }}>
              {displayStatus}
              {decision.human_reviewed && ' · Human reviewed'}
            </div>
          </div>
        </div>
        <div
          className="nf-score"
          style={{
            color: dc === 'approve' ? 'var(--nf-success)' : dc === 'review' ? 'var(--nf-warning)' : 'var(--nf-red)',
          }}
        >
          {risk.risk_score ?? 0}
        </div>
      </div>

      <div className={`nf-profile-explanation ${dc}`}>
        <h2>Profile Summary</h2>
        <p>{summary}</p>
        {result.explanation?.narrative && (
          <div className="nf-narrative">{result.explanation.narrative}</div>
        )}
      </div>

      <div className="nf-card">
        <h3>
          {status === 'APPROVE' ? 'Approval Reasons' : status === 'REVIEW' ? 'Review Reasons' : 'Escalation Reasons'}
          {decision.groq_powered && (
            <span className="nf-profile-groq-tag">
              <Sparkles size={12} />
              Groq AI
            </span>
          )}
        </h3>
        <div className="nf-profile-reasons">
          {reasons.map((r, i) => (
            <div key={i} className={`nf-profile-reason ${r.severity}`}>
              <span className="nf-profile-reason-label">{r.label}</span>
              <span className="nf-profile-reason-detail">{r.detail}</span>
            </div>
          ))}
        </div>
      </div>

      {result.edd_triggered && (
        <div className="nf-card nf-edd-card">
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
          {result.edd_summary && <p className="nf-edd-summary">{result.edd_summary}</p>}
        </div>
      )}

      {result.consistency_summary && (() => {
        const band = consistencyBand(result.consistency_score)
        const issues = sortBySeverity(result.consistency_issues || [])
        return (
          <div className={`nf-card nf-consistency-card ${band}`}>
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

      <div className="nf-grid-2 nf-profile-detail-grid">
        <div className="nf-card">
          <h3><User size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: -2 }} />Customer Profile</h3>
          <div className="nf-profile-grid">
            {PROFILE_KEYS.map((key) => {
              const fs = fieldStatus?.[key]
              const rawVal = customerProfile[key] || ''
              const val = key === 'nationality' ? countryLabel(rawVal) : rawVal
              const missing = fs?.status === 'missing' || (!rawVal && key !== 'intake_confidence')
              return (
                <div
                  key={key}
                  className={`nf-profile-field ${missing ? (fs?.required ? 'missing-required' : 'missing-optional') : ''}`}
                >
                  <label>{PROFILE_LABELS[key] || fs?.label || key.replace(/_/g, ' ')}</label>
                  <span className={missing ? 'missing-value' : ''}>{val || '—'}</span>
                </div>
              )
            })}
          </div>
        </div>

        <div className="nf-card">
          <h3><Shield size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: -2 }} />Risk Assessment</h3>
          <div className="nf-profile-risk-meta">
            <span>Risk level: <strong>{risk.risk_level || 'Unknown'}</strong></span>
            {risk.scoring_method && (
              <span>
                Method:{' '}
                <strong>
                  {risk.scoring_method === 'hybrid' ? 'Hybrid (XGBoost + Rules)' : 'Rule-based'}
                </strong>
              </span>
            )}
            {hasConfidence(result.overall_confidence) && (() => {
              const band = confidenceBand(result.overall_confidence)
              return (
                <span>
                  Confidence:{' '}
                  <strong>{confidenceIcon(band)} {confidencePct(result.overall_confidence)}% · {confidenceLabel(band)}</strong>
                </span>
              )
            })()}
          </div>
          {breakdown.length > 0 ? breakdown.map((b, i) => (
            <div key={i} className={`nf-breakdown-item ${b.source === 'ml' ? 'nf-breakdown-ml' : ''}`}>
              <span>{b.signal}</span>
              <span className="pts">+{b.points}</span>
            </div>
          )) : (
            <p style={{ fontSize: '0.85rem', color: 'var(--nf-dim)' }}>No risk breakdown available for this profile.</p>
          )}
        </div>
      </div>

      <EvidenceDetailSection result={result} />

      {Boolean(result.groq_verification?.summary) && (
        <div className="nf-card">
          <h3><Sparkles size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: -2 }} />Groq Profile Check</h3>
          <p style={{ fontSize: '0.9rem', color: 'var(--nf-muted)', marginTop: '0.5rem' }}>
            {String(result.groq_verification.summary)}
          </p>
        </div>
      )}
    </>
  )
}

export default function ProfileDetailPage({ onRefresh }: { onRefresh?: () => void }) {
  const { caseId: rawCaseId } = useParams<{ caseId: string }>()
  const caseId = rawCaseId ? decodeURIComponent(rawCaseId).trim() : ''
  const [result, setResult] = useState<KYCResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!caseId) {
      setResult(null)
      setError('Invalid profile ID')
      setLoading(false)
      return
    }

    const controller = new AbortController()
    setLoading(true)
    setError('')
    setResult(null)

    fetchCase(caseId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setResult(data)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Profile not found')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [caseId])

  if (loading) {
    return (
      <ProfileShell caseId={caseId} title="Loading profile…">
        <div className="nf-card nf-empty">
          <p>Fetching verification data…</p>
        </div>
      </ProfileShell>
    )
  }

  if (error || !result) {
    return (
      <ProfileShell caseId={caseId || undefined} title="Profile Not Found">
        <div className="nf-card nf-empty">
          <User size={40} style={{ opacity: 0.2, margin: '0 auto 1rem' }} />
          <p>{error || 'Profile not found'}</p>
        </div>
      </ProfileShell>
    )
  }

  const status = getProfileStatus(result)
  const title = result.customer_profile?.name || 'Customer Profile'

  return (
    <ProfileShell caseId={result.case_id} title={title} statusClass={decisionClass(status)}>
      <ErrorBoundary>
        <ProfileDetailContent
          result={result}
          onReviewComplete={(updated) => {
            setResult(updated)
            onRefresh?.()
          }}
        />
      </ErrorBoundary>
    </ProfileShell>
  )
}
