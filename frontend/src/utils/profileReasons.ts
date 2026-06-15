import { KYCResult } from '../api'

export type ProfileStatus = 'APPROVE' | 'REVIEW' | 'ESCALATE'

export interface ProfileReason {
  label: string
  detail: string
  severity: 'high' | 'medium' | 'positive'
}

function asStringList(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  return values.filter((v): v is string => typeof v === 'string' && v.length > 0)
}

export function getProfileStatus(result: KYCResult): ProfileStatus {
  const decision = result.decision ?? {}
  const raw = String(decision.final_status || decision.status || 'PENDING').toUpperCase()
  if (raw.includes('APPROVE')) return 'APPROVE'
  if (raw === 'REVIEW') return 'REVIEW'
  if (raw === 'ESCALATE') return 'ESCALATE'
  if (decision.requires_human_review) return 'REVIEW'
  return 'ESCALATE'
}

export function getStatusSummary(status: ProfileStatus, result: KYCResult): string {
  const name = result.customer_profile?.name || 'This customer'
  switch (status) {
    case 'APPROVE':
      return `${name}'s profile meets compliance requirements. Automated KYC checks, document validation, and risk scoring indicate this case is suitable for approval.`
    case 'REVIEW':
      return `${name}'s profile is flagged for manual review. Additional verification is recommended before onboarding due to moderate risk indicators.`
    case 'ESCALATE':
      return `${name}'s profile requires escalation to a senior compliance officer. Critical risk signals or document failures were detected during verification.`
  }
}

export function collectReasons(result: KYCResult): ProfileReason[] {
  const status = getProfileStatus(result)
  const reasons: ProfileReason[] = []
  const decision = result.decision ?? {}
  const riskScore = result.risk_assessment?.risk_score ?? 0
  const breakdown = result.risk_assessment?.breakdown ?? []

  if (status === 'APPROVE') {
    if (result.document_verdict?.verdict === 'VERIFIED') {
      reasons.push({
        label: 'Documents',
        detail: result.document_verdict.summary || 'All uploaded identity documents passed verification.',
        severity: 'positive',
      })
    } else if (result.document_verdict?.summary) {
      reasons.push({ label: 'Documents', detail: result.document_verdict.summary, severity: 'positive' })
    }

    if (riskScore < 40) {
      reasons.push({
        label: 'Risk Score',
        detail: `Risk score of ${riskScore} is below the review threshold (40).`,
        severity: 'positive',
      })
    }

    asStringList(decision.reasons || result.explanation?.reasons).forEach((r) => {
      reasons.push({ label: 'Compliance', detail: r, severity: 'positive' })
    })

    if (decision.human_reviewed && String(decision.final_status || '').includes('OVERRIDE')) {
      reasons.push({
        label: 'Human Review',
        detail: 'A compliance officer reviewed and approved this profile despite initial flags.',
        severity: 'positive',
      })
    }

    if (reasons.length === 0) {
      reasons.push({
        label: 'Clearance',
        detail: 'No adverse screening hits, document failures, or high-risk signals were detected.',
        severity: 'positive',
      })
    }
    return reasons
  }

  const groqReasons = asStringList(decision.reasons || result.explanation?.reasons)
    .filter((r) => !r.startsWith('Document verification failed'))

  if (result.document_rejected && result.document_verdict?.rejection_reasons?.length) {
    asStringList(result.document_verdict.rejection_reasons)
      .filter((r) => !r.startsWith('  └'))
      .forEach((r) => reasons.push({ label: 'Document', detail: r, severity: 'high' }))
  }

  groqReasons.forEach((r) => {
    const lower = r.toLowerCase()
    reasons.push({
      label: decision.groq_powered ? 'Groq AI' : 'Risk Signal',
      detail: r,
      severity:
        lower.includes('sanctions') || lower.includes('pep') || lower.includes('mismatch') || lower.includes('document')
          ? 'high'
          : 'medium',
    })
  })

  if (decision.id_mismatch?.detected || result.document_verdict?.id_mismatch || result.explanation?.id_mismatch) {
    reasons.push({
      label: 'ID Mismatch',
      detail:
        decision.id_mismatch?.reason
        || result.explanation?.id_mismatch?.short_reason
        || 'The declared ID number does not match the uploaded document.',
      severity: 'high',
    })
  }

  if (!groqReasons.length && breakdown.length > 0 && !result.document_rejected) {
    breakdown
      .filter((b) => b.source !== 'ml' && b.points >= 10)
      .forEach((b) => {
        reasons.push({
          label: 'Risk Factor',
          detail: b.signal,
          severity: b.points >= 25 ? 'high' : 'medium',
        })
      })
  }

  if (result.missing_fields?.length) {
    reasons.push({
      label: 'Incomplete Profile',
      detail: `Missing fields: ${result.missing_fields.map((f) => f.replace(/_/g, ' ')).join(', ')}.`,
      severity: 'medium',
    })
  }

  if (decision.requires_human_review && !decision.human_reviewed) {
    reasons.push({
      label: 'Human Review',
      detail: 'This case is awaiting compliance officer decision.',
      severity: status === 'ESCALATE' ? 'high' : 'medium',
    })
  }

  if (reasons.length === 0) {
    reasons.push({
      label: 'Decision',
      detail: status === 'ESCALATE'
        ? 'Profile escalated due to elevated risk score or compliance policy triggers.'
        : 'Profile flagged for review based on automated risk assessment.',
      severity: status === 'ESCALATE' ? 'high' : 'medium',
    })
  }

  return reasons
}
