import { StoredCase } from '../api'

export function decisionClass(s: string) {
  if (s === 'APPROVE' || s.includes('APPROVE')) return 'approve'
  if (s === 'REVIEW') return 'review'
  return 'escalate'
}

export function effectiveDecision(c: StoredCase): 'APPROVE' | 'REVIEW' | 'ESCALATE' {
  const raw = (c.final_status || c.decision || 'PENDING').toUpperCase()
  if (raw.includes('APPROVE')) return 'APPROVE'
  if (raw === 'REVIEW') return 'REVIEW'
  if (raw === 'ESCALATE') return 'ESCALATE'
  if (c.requires_review) return 'REVIEW'
  return 'ESCALATE'
}

export function decisionLabel(status: 'APPROVE' | 'REVIEW' | 'ESCALATE') {
  if (status === 'APPROVE') return 'Approved'
  if (status === 'REVIEW') return 'In Review'
  return 'Escalated'
}

export function needsHumanReview(c: StoredCase): boolean {
  return c.requires_review && !c.human_reviewed
}
