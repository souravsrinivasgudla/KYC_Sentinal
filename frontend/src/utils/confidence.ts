// Shared confidence display helpers (Phase 2).
// Confidence is 0–1 from the backend; legacy cases may omit it (undefined).

export type ConfidenceBand = 'high' | 'moderate' | 'low' | 'none'

export const AGENT_CONFIDENCE_LABELS: Record<string, string> = {
  document_verification: 'Document Verification',
  entity_resolution: 'Entity Resolution',
  compliance_screening: 'Compliance Screening',
  evidence_validation: 'Evidence Validation',
  adverse_media: 'Adverse Media',
  financial_profiling: 'Financial Profiling',
}

/** Display order for the breakdown (matches aggregation weighting order). */
export const AGENT_CONFIDENCE_ORDER = [
  'document_verification',
  'entity_resolution',
  'compliance_screening',
  'evidence_validation',
  'adverse_media',
  'financial_profiling',
]

export function hasConfidence(value?: number): boolean {
  return typeof value === 'number' && value > 0
}

export function confidenceBand(value?: number): ConfidenceBand {
  if (!hasConfidence(value)) return 'none'
  const v = value as number
  if (v >= 0.9) return 'high'
  if (v >= 0.7) return 'moderate'
  return 'low'
}

export function confidencePct(value?: number): number {
  return Math.round((value ?? 0) * 100)
}

export function confidenceLabel(band: ConfidenceBand): string {
  switch (band) {
    case 'high': return 'High Confidence'
    case 'moderate': return 'Moderate Confidence'
    case 'low': return 'Low Confidence'
    default: return 'Confidence Unavailable'
  }
}

/** ✓ for high, ⚠ for moderate/low (per spec). */
export function confidenceIcon(band: ConfidenceBand): string {
  return band === 'high' ? '✓' : band === 'none' ? '—' : '⚠'
}

export function confidenceExplanation(band: ConfidenceBand): string {
  switch (band) {
    case 'high':
      return 'Automated findings are strongly supported by the verification agents.'
    case 'moderate':
      return 'Findings are reasonably supported; review the supporting evidence.'
    case 'low':
      return 'Findings rely on lower-confidence signals and should be reviewed carefully.'
    default:
      return 'No confidence signals were available for this case.'
  }
}

/** Advisory-only guidance shown in the Human Review panel. */
export function reviewerGuidance(band: ConfidenceBand): string {
  switch (band) {
    case 'high': return 'Automated findings are strongly supported.'
    case 'moderate': return 'Review supporting evidence carefully.'
    case 'low': return 'Additional investigation recommended.'
    default: return 'Confidence data unavailable — apply standard review judgement.'
  }
}
