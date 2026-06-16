// Risk contribution display helpers (Phase 3). Display only — never affects score.
import { RiskContribution } from '../api'

/** Format an impact as a signed string: 25 -> "+25", -5 -> "-5". */
export function formatImpact(impact: number): string {
  return impact >= 0 ? `+${impact}` : `${impact}`
}

/** Largest absolute impact in the list (for scaling progress bars). Min 1 to avoid /0. */
export function maxAbsImpact(contributions: RiskContribution[]): number {
  return Math.max(1, ...contributions.map((c) => Math.abs(c.impact)))
}

/** Bar width % for a contribution, relative to the largest contributor. */
export function impactBarWidth(impact: number, max: number): number {
  return Math.round((Math.abs(impact) / max) * 100)
}
