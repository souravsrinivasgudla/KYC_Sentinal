// Consistency display helpers (Phase 5). Display only — never affects decisions.

export type ConsistencyBand = 'consistent' | 'minor' | 'significant'

export function consistencyBand(score?: number): ConsistencyBand {
  const v = typeof score === 'number' ? score : 1
  if (v >= 0.9) return 'consistent'
  if (v >= 0.7) return 'minor'
  return 'significant'
}

export function consistencyPct(score?: number): number {
  return Math.round((typeof score === 'number' ? score : 1) * 100)
}

export function consistencyLabel(band: ConsistencyBand): string {
  switch (band) {
    case 'consistent': return 'Consistent'
    case 'minor': return 'Minor Inconsistencies'
    case 'significant': return 'Significant Inconsistencies'
  }
}

export function consistencyIcon(band: ConsistencyBand): string {
  return band === 'consistent' ? '✓' : '⚠'
}

const SEVERITY_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 }

/** Sort issues by severity (high → low); backend already sorts, this is defensive. */
export function sortBySeverity<T extends { severity: string }>(issues: T[]): T[] {
  return [...issues].sort((a, b) => (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0))
}
