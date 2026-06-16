import { StoredCase } from '../api'
import { decisionLabel, effectiveDecision } from './decision'

export type DecisionKey = 'APPROVE' | 'REVIEW' | 'ESCALATE'

export interface DashboardStats {
  total: number
  approved: number
  inReview: number
  escalated: number
  acceptanceRate: number
  reviewRate: number
  rejectionRate: number
  nonApprovedRate: number
  pendingHumanReview: number
  humanReviewed: number
  autoApproved: number
  avgRiskScore: number
  withMissingFields: number
  riskLevels: { label: string; count: number; color: string }[]
  riskScoreBuckets: { label: string; count: number; color: string; min: number; max: number }[]
  decisions: { key: DecisionKey; label: string; count: number; rate: number; color: string }[]
  timeline: { label: string; count: number; approved: number; review: number; escalated: number }[]
  recentActivity: {
    caseId: string
    name: string
    decision: DecisionKey
    riskScore: number
    createdAt: string
  }[]
}

const DECISION_COLORS: Record<DecisionKey, string> = {
  APPROVE: '#46d369',
  REVIEW: '#e8a317',
  ESCALATE: '#e50914',
}

const RISK_COLORS: Record<string, string> = {
  Low: '#46d369',
  Medium: '#e8a317',
  High: '#e50914',
  Unknown: '#808080',
}

const SCORE_BUCKETS = [
  { label: '0–39 Low', min: 0, max: 39, color: '#46d369' },
  { label: '40–69 Medium', min: 40, max: 69, color: '#e8a317' },
  { label: '70–100 High', min: 70, max: 100, color: '#e50914' },
]

function pct(n: number, total: number): number {
  if (total === 0) return 0
  return Math.round((n / total) * 1000) / 10
}

function dayKey(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 10)
  } catch {
    return iso.slice(0, 10)
  }
}

function formatDayLabel(key: string): string {
  try {
    return new Date(key + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return key
  }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function computeDashboardStats(cases: StoredCase[]): DashboardStats {
  const total = cases.length
  let approved = 0
  let inReview = 0
  let escalated = 0
  let pendingHumanReview = 0
  let humanReviewed = 0
  let autoApproved = 0
  let riskSum = 0
  let withMissingFields = 0

  const riskMap = new Map<string, number>()
  const bucketCounts = SCORE_BUCKETS.map(() => 0)
  const dayMap = new Map<string, { count: number; approved: number; review: number; escalated: number }>()

  for (const c of cases) {
    const decision = effectiveDecision(c)
    if (decision === 'APPROVE') approved += 1
    else if (decision === 'REVIEW') inReview += 1
    else escalated += 1

    if (c.requires_review && !c.human_reviewed) pendingHumanReview += 1
    if (c.human_reviewed) humanReviewed += 1
    if (!c.requires_review && decision === 'APPROVE') autoApproved += 1

    const score = c.risk_score ?? 0
    riskSum += score
    if (c.missing_fields?.length > 0) withMissingFields += 1

    const rl = c.risk_level || 'Unknown'
    riskMap.set(rl, (riskMap.get(rl) ?? 0) + 1)

    const bi = SCORE_BUCKETS.findIndex((b) => score >= b.min && score <= b.max)
    if (bi >= 0) bucketCounts[bi] += 1

    const dk = dayKey(c.created_at)
    const bucket = dayMap.get(dk) ?? { count: 0, approved: 0, review: 0, escalated: 0 }
    bucket.count += 1
    if (decision === 'APPROVE') bucket.approved += 1
    else if (decision === 'REVIEW') bucket.review += 1
    else bucket.escalated += 1
    dayMap.set(dk, bucket)
  }

  const sortedDays = [...dayMap.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  const recentDays = sortedDays.slice(-14)

  const recentActivity = [...cases]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 8)
    .map((c) => ({
      caseId: c.case_id,
      name: c.customer_name,
      decision: effectiveDecision(c),
      riskScore: c.risk_score ?? 0,
      createdAt: formatTime(c.created_at),
    }))

  return {
    total,
    approved,
    inReview,
    escalated,
    acceptanceRate: pct(approved, total),
    reviewRate: pct(inReview, total),
    rejectionRate: pct(escalated, total),
    nonApprovedRate: pct(inReview + escalated, total),
    pendingHumanReview,
    humanReviewed,
    autoApproved,
    avgRiskScore: total ? Math.round((riskSum / total) * 10) / 10 : 0,
    withMissingFields,
    riskLevels: ['Low', 'Medium', 'High', 'Unknown']
      .map((label) => ({ label, count: riskMap.get(label) ?? 0, color: RISK_COLORS[label] }))
      .filter((r) => r.count > 0),
    riskScoreBuckets: SCORE_BUCKETS.map((b, i) => ({
      ...b,
      count: bucketCounts[i],
    })),
    decisions: (['APPROVE', 'REVIEW', 'ESCALATE'] as DecisionKey[]).map((key) => {
      const count = key === 'APPROVE' ? approved : key === 'REVIEW' ? inReview : escalated
      return {
        key,
        label: decisionLabel(key),
        count,
        rate: pct(count, total),
        color: DECISION_COLORS[key],
      }
    }),
    timeline: recentDays.map(([key, v]) => ({
      label: formatDayLabel(key),
      count: v.count,
      approved: v.approved,
      review: v.review,
      escalated: v.escalated,
    })),
    recentActivity,
  }
}

export function donutSegments(stats: DashboardStats): { color: string; percent: number }[] {
  if (stats.total === 0) return []
  return stats.decisions
    .filter((d) => d.count > 0)
    .map((d) => ({
      color: d.color,
      percent: (d.count / stats.total) * 100,
    }))
}
