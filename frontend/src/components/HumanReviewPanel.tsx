import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { ConsistencyIssue, KYCResult, RiskContribution, submitReview } from '../api'
import {
  confidenceBand,
  confidenceIcon,
  confidenceLabel,
  confidencePct,
  hasConfidence,
  reviewerGuidance,
} from '../utils/confidence'
import { formatImpact } from '../utils/riskBreakdown'

interface Props {
  caseId: string
  briefing?: string
  confidence?: number
  topRiskDrivers?: RiskContribution[]
  eddSummary?: string
  consistencyIssues?: ConsistencyIssue[]
  recommendation?: {
    suggested_action: 'APPROVE' | 'REJECT' | 'REVIEW'
    headline: string
    reason: string
  } | null
  onAskCopilot?: () => void
  compact?: boolean
  onComplete?: (result: KYCResult) => void
}

export default function HumanReviewPanel({ caseId, briefing, confidence, topRiskDrivers, eddSummary, consistencyIssues, recommendation, onAskCopilot, compact = false, onComplete }: Props) {
  const [comment, setComment] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleReview = async (action: string) => {
    setLoading(true)
    setError('')
    try {
      const updated = await submitReview(caseId, action, comment, 'Compliance Analyst')
      onComplete?.(updated)
    } catch {
      setError('Review submission failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className={`nf-review ${compact ? 'nf-review-compact' : 'nf-card'}`}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      role="presentation"
    >
      <h3>{compact ? 'Human Review' : 'Human Review Required'}</h3>
      {recommendation && (
        <div className={`nf-review-reco ${recommendation.suggested_action.toLowerCase()}`}>
          <div className="nf-review-reco-head">
            System recommendation: <strong>{recommendation.headline}</strong>
          </div>
          <p>{recommendation.reason}</p>
        </div>
      )}
      {eddSummary && (
        <div className="nf-review-edd">
          <div className="nf-review-edd-title">Enhanced Due Diligence</div>
          <p>{eddSummary}</p>
        </div>
      )}
      {(consistencyIssues?.length ?? 0) > 0 && (
        <div className="nf-review-consistency">
          <div className="nf-review-consistency-title">Consistency Findings</div>
          <ul>
            {consistencyIssues!.map((iss, i) => (
              <li key={i}>
                <span className={`nf-consistency-sev ${iss.severity}`}>{iss.severity.toUpperCase()}</span>
                <span>{iss.description}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasConfidence(confidence) && (() => {
        const band = confidenceBand(confidence)
        return (
          <div className={`nf-review-confidence ${band}`}>
            <div className="nf-review-confidence-head">
              <span>Overall Confidence</span>
              <strong>{confidenceIcon(band)} {confidencePct(confidence)}% · {confidenceLabel(band)}</strong>
            </div>
            <p className="nf-review-confidence-guidance">{reviewerGuidance(band)}</p>
          </div>
        )
      })()}
      {(topRiskDrivers?.length ?? 0) > 0 && (
        <div className="nf-review-drivers">
          <div className="nf-review-drivers-title">Top Risk Drivers</div>
          <ul>
            {topRiskDrivers!.map((d, i) => (
              <li key={i}>
                <span>{d.factor}</span>
                <span className="nf-review-drivers-impact">{formatImpact(d.impact)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {briefing && (
        <p className="nf-review-briefing">
          <Sparkles size={14} />
          {briefing}
        </p>
      )}
      {onAskCopilot && (
        <button type="button" className="nf-review-copilot-btn" onClick={onAskCopilot}>
          <Sparkles size={13} /> Ask Copilot
        </button>
      )}
      <textarea
        placeholder="Officer comments..."
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        disabled={loading}
      />
      {error && <p className="nf-review-error">{error}</p>}
      <div className="nf-review-actions">
        <button
          type="button"
          className="nf-btn-sm nf-btn-approve"
          disabled={loading}
          onClick={() => handleReview('approve')}
        >
          Approve
        </button>
        <button
          type="button"
          className="nf-btn-sm nf-btn-override"
          disabled={loading}
          onClick={() => handleReview('override')}
        >
          Override
        </button>
        <button
          type="button"
          className="nf-btn-sm nf-btn-escalate"
          disabled={loading}
          onClick={() => handleReview('escalate')}
        >
          Escalate
        </button>
      </div>
    </div>
  )
}
