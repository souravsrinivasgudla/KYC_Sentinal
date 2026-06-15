import { History, User } from 'lucide-react'
import { StoredCase } from '../api'

interface Props {
  cases: StoredCase[]
  selectedCaseId: string | null
  onSelect: (caseId: string) => void
}

function decisionColor(decision: string) {
  if (decision === 'APPROVE') return 'var(--success)'
  if (decision === 'REVIEW') return 'var(--warning)'
  return 'var(--danger)'
}

export default function VerificationHistory({ cases, selectedCaseId, onSelect }: Props) {
  if (!cases.length) return null

  return (
    <div className="card">
      <h3><History size={14} style={{ display: 'inline', marginRight: 6, verticalAlign: -2 }} />Verification History</h3>
      <div className="history-list">
        {cases.map((c) => (
          <div
            key={c.case_id}
            className={`history-item ${selectedCaseId === c.case_id ? 'active' : ''}`}
            onClick={() => onSelect(c.case_id)}
          >
            <div className="history-icon"><User size={14} /></div>
            <div className="history-info">
              <div className="history-name">{c.customer_name}</div>
              <div className="history-meta">
                {c.case_id} · {c.source}
                {c.missing_fields?.length > 0 && (
                  <span className="history-missing-tag"> · {c.missing_fields.length} missing</span>
                )}
              </div>
            </div>
            <div className="history-right">
              <span className="history-score" style={{ color: decisionColor(c.decision) }}>{c.risk_score}</span>
              <span className="history-decision" style={{ color: decisionColor(c.decision) }}>{c.decision}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
