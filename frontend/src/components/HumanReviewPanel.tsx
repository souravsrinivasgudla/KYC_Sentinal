import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { KYCResult, submitReview } from '../api'

interface Props {
  caseId: string
  briefing?: string
  compact?: boolean
  onComplete?: (result: KYCResult) => void
}

export default function HumanReviewPanel({ caseId, briefing, compact = false, onComplete }: Props) {
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
      {briefing && (
        <p className="nf-review-briefing">
          <Sparkles size={14} />
          {briefing}
        </p>
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
