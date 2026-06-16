import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BarChart3,
  CheckCircle,
  AlertTriangle,
  XCircle,
  TrendingUp,
  Users,
  Shield,
  Clock,
  Activity,
  RefreshCw,
} from 'lucide-react'
import { fetchCases, StoredCase } from '../api'
import { decisionClass } from '../utils/decision'
import { computeDashboardStats, donutSegments } from '../utils/dashboardStats'

const POLL_MS = 8000

function DonutChart({ segments, total, size = 200 }: { segments: ReturnType<typeof donutSegments>; total: number; size?: number }) {
  const r = 72
  const c = 2 * Math.PI * r
  const cx = 100
  const cy = 100
  let dashOffset = 0

  if (total === 0) {
    return (
      <svg viewBox="0 0 200 200" className="nf-dash-donut" style={{ width: size, height: size }}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="22" />
        <text x={cx} y={cy + 6} textAnchor="middle" fill="var(--nf-dim)" fontSize="14">No data yet</text>
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 200 200" className="nf-dash-donut" style={{ width: size, height: size }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="22" />
      {segments.map((seg, i) => {
        const dash = (seg.percent / 100) * c
        const el = (
          <circle
            key={i}
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={seg.color}
            strokeWidth="22"
            strokeDasharray={`${dash} ${c - dash}`}
            strokeDashoffset={-dashOffset}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        )
        dashOffset += dash
        return el
      })}
      <text x={cx} y={cy - 4} textAnchor="middle" fill="var(--nf-text)" fontSize="32" fontWeight="700">
        {total}
      </text>
      <text x={cx} y={cy + 20} textAnchor="middle" fill="var(--nf-dim)" fontSize="12">
        total profiles
      </text>
    </svg>
  )
}

function GaugeRing({ value, label, color }: { value: number; label: string; color: string }) {
  const r = 56
  const c = 2 * Math.PI * r
  const dash = (Math.min(value, 100) / 100) * c

  return (
    <div className="nf-dash-gauge">
      <svg viewBox="0 0 140 140" className="nf-dash-gauge-svg">
        <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="14" />
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="14"
          strokeDasharray={`${dash} ${c}`}
          transform="rotate(-90 70 70)"
          strokeLinecap="round"
        />
        <text x="70" y="68" textAnchor="middle" fill="var(--nf-text)" fontSize="22" fontWeight="700">
          {value}%
        </text>
        <text x="70" y="88" textAnchor="middle" fill="var(--nf-dim)" fontSize="10">
          {label}
        </text>
      </svg>
    </div>
  )
}

function VerticalBars({ stats }: { stats: ReturnType<typeof computeDashboardStats> }) {
  const max = Math.max(1, ...stats.decisions.map((d) => d.count))

  return (
    <div className="nf-dash-vbars">
      {stats.decisions.map((d) => (
        <div key={d.key} className="nf-dash-vbar-col">
          <span className="nf-dash-vbar-count">{d.count}</span>
          <div className="nf-dash-vbar-track">
            <div
              className="nf-dash-vbar-fill"
              style={{ height: `${(d.count / max) * 100}%`, background: d.color }}
            />
          </div>
          <span className="nf-dash-vbar-label">{d.label}</span>
          <span className="nf-dash-vbar-rate">{d.rate}%</span>
        </div>
      ))}
    </div>
  )
}

export default function DashboardPage() {
  const [cases, setCases] = useState<StoredCase[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await fetchCases()
      setCases(data)
      setLastUpdated(new Date())
    } catch {
      /* keep previous data on poll failure */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = window.setInterval(load, POLL_MS)
    return () => window.clearInterval(id)
  }, [load])

  const stats = useMemo(() => computeDashboardStats(cases), [cases])
  const segments = useMemo(() => donutSegments(stats), [stats])
  const maxTimeline = Math.max(1, ...stats.timeline.map((t) => t.count))
  const maxBucket = Math.max(1, ...stats.riskScoreBuckets.map((b) => b.count))

  return (
    <>
      <section className="nf-hero nf-hero-compact">
        <div className="nf-hero-content nf-dash-hero-row">
          <div>
            <h1>Compliance <span>Dashboard</span></h1>
            <p>Live analytics from all KYC verifications — updates automatically every few seconds.</p>
          </div>
          <div className="nf-dash-live-badge">
            <span className="nf-dash-live-dot" />
            <span className="nf-dash-live-label">Live</span>
            {lastUpdated && (
              <span className="nf-dash-live-time">
                <span>Updated</span>
                <time dateTime={lastUpdated.toISOString()}>
                  {lastUpdated.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </time>
              </span>
            )}
            <button type="button" className="nf-dash-refresh" onClick={load} title="Refresh now">
              <RefreshCw size={14} className={loading ? 'nf-spin' : ''} />
            </button>
          </div>
        </div>
      </section>

      <main className="nf-main nf-dashboard">
        <div className="nf-dash-kpis">
          <div className="nf-dash-kpi">
            <Users size={28} />
            <div>
              <span className="nf-dash-kpi-label">Total Verifications</span>
              <strong className="nf-dash-kpi-value">{stats.total}</strong>
            </div>
          </div>
          <div className="nf-dash-kpi approve">
            <CheckCircle size={28} />
            <div>
              <span className="nf-dash-kpi-label">Approved</span>
              <strong className="nf-dash-kpi-value">{stats.approved}</strong>
              <span className="nf-dash-kpi-sub">{stats.acceptanceRate}% acceptance rate</span>
            </div>
          </div>
          <div className="nf-dash-kpi review">
            <AlertTriangle size={28} />
            <div>
              <span className="nf-dash-kpi-label">In Review</span>
              <strong className="nf-dash-kpi-value">{stats.inReview}</strong>
              <span className="nf-dash-kpi-sub">{stats.reviewRate}% of all cases</span>
            </div>
          </div>
          <div className="nf-dash-kpi escalate">
            <XCircle size={28} />
            <div>
              <span className="nf-dash-kpi-label">Escalated</span>
              <strong className="nf-dash-kpi-value">{stats.escalated}</strong>
              <span className="nf-dash-kpi-sub">{stats.rejectionRate}% rejection rate</span>
            </div>
          </div>
        </div>

        <div className="nf-dash-grid">
          <div className="nf-card nf-dash-panel nf-dash-panel-lg">
            <div className="nf-dash-panel-head">
              <BarChart3 size={20} />
              <h2>Decision Distribution</h2>
            </div>
            <div className="nf-dash-split">
              <DonutChart segments={segments} total={stats.total} size={220} />
              <VerticalBars stats={stats} />
            </div>
          </div>

          <div className="nf-card nf-dash-panel nf-dash-panel-lg">
            <div className="nf-dash-panel-head">
              <TrendingUp size={20} />
              <h2>Outcome Rates</h2>
            </div>
            <div className="nf-dash-gauges">
              <GaugeRing value={stats.acceptanceRate} label="Acceptance" color="#46d369" />
              <GaugeRing value={stats.reviewRate} label="In review" color="#e8a317" />
              <GaugeRing value={stats.rejectionRate} label="Escalated" color="#e50914" />
            </div>
            <div className="nf-dash-rate-bars">
              {[
                { label: 'Acceptance', rate: stats.acceptanceRate, color: '#46d369', count: stats.approved },
                { label: 'Review', rate: stats.reviewRate, color: '#e8a317', count: stats.inReview },
                { label: 'Rejection', rate: stats.rejectionRate, color: '#e50914', count: stats.escalated },
              ].map((row) => (
                <div key={row.label} className="nf-dash-rate-row">
                  <div className="nf-dash-rate-head">
                    <span>{row.label}</span>
                    <span className="nf-dash-rate-val" style={{ color: row.color }}>{row.rate}%</span>
                  </div>
                  <div className="nf-dash-rate-track nf-dash-rate-track-lg">
                    <div className="nf-dash-rate-fill" style={{ width: `${row.rate}%`, background: row.color }} />
                  </div>
                  <span className="nf-dash-rate-count">{row.count} profiles</span>
                </div>
              ))}
            </div>
          </div>

          <div className="nf-card nf-dash-panel nf-dash-panel-wide nf-dash-panel-lg">
            <div className="nf-dash-panel-head">
              <Activity size={20} />
              <h2>Verifications Over Time</h2>
              <span className="nf-dash-panel-note">{stats.timeline.length} active days</span>
            </div>
            {stats.timeline.length === 0 ? (
              <p className="nf-dash-empty">No verification history yet. Run a KYC check from Home.</p>
            ) : (
              <div className="nf-dash-timeline nf-dash-timeline-lg">
                {stats.timeline.map((day) => (
                  <div key={day.label} className="nf-dash-timeline-col">
                    <span className="nf-dash-timeline-count">{day.count}</span>
                    <div className="nf-dash-timeline-bars">
                      <div
                        className="nf-dash-timeline-bar approve"
                        style={{ height: `${(day.approved / maxTimeline) * 100}%` }}
                        title={`Approved: ${day.approved}`}
                      />
                      <div
                        className="nf-dash-timeline-bar review"
                        style={{ height: `${(day.review / maxTimeline) * 100}%` }}
                        title={`In review: ${day.review}`}
                      />
                      <div
                        className="nf-dash-timeline-bar escalate"
                        style={{ height: `${(day.escalated / maxTimeline) * 100}%` }}
                        title={`Escalated: ${day.escalated}`}
                      />
                    </div>
                    <span className="nf-dash-timeline-label">{day.label}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="nf-dash-timeline-legend">
              <span><i className="approve" /> Approved</span>
              <span><i className="review" /> In review</span>
              <span><i className="escalate" /> Escalated</span>
            </div>
          </div>

          <div className="nf-card nf-dash-panel nf-dash-panel-lg">
            <div className="nf-dash-panel-head">
              <Shield size={20} />
              <h2>Risk Score Distribution</h2>
            </div>
            <div className="nf-dash-histogram">
              {stats.riskScoreBuckets.map((b) => (
                <div key={b.label} className="nf-dash-hist-col">
                  <span className="nf-dash-hist-val">{b.count}</span>
                  <div className="nf-dash-hist-bar-wrap">
                    <div
                      className="nf-dash-hist-bar"
                      style={{
                        height: `${(b.count / maxBucket) * 100}%`,
                        background: b.color,
                      }}
                    />
                  </div>
                  <span className="nf-dash-hist-label">{b.label}</span>
                </div>
              ))}
            </div>
            {stats.riskLevels.length > 0 && (
              <div className="nf-dash-risk-bars">
                {stats.riskLevels.map((r) => {
                  const p = stats.total ? (r.count / stats.total) * 100 : 0
                  return (
                    <div key={r.label} className="nf-dash-risk-row">
                      <span>{r.label} risk</span>
                      <div className="nf-dash-risk-track nf-dash-risk-track-lg">
                        <div className="nf-dash-risk-fill" style={{ width: `${p}%`, background: r.color }} />
                      </div>
                      <strong>{r.count}</strong>
                    </div>
                  )
                })}
              </div>
            )}
            <p className="nf-dash-metric-line">
              Average risk score: <strong>{stats.avgRiskScore}</strong> / 100
            </p>
          </div>

          <div className="nf-card nf-dash-panel nf-dash-panel-lg">
            <div className="nf-dash-panel-head">
              <Clock size={20} />
              <h2>Operational Metrics</h2>
            </div>
            <div className="nf-dash-metrics-grid">
              {[
                { label: 'Pending human review', value: stats.pendingHumanReview, warn: stats.pendingHumanReview > 0 },
                { label: 'Officer reviewed', value: stats.humanReviewed, warn: false },
                { label: 'Auto-approved', value: stats.autoApproved, warn: false },
                { label: 'Missing fields flagged', value: stats.withMissingFields, warn: stats.withMissingFields > 0 },
                { label: 'Non-approved rate', value: `${stats.nonApprovedRate}%`, warn: stats.nonApprovedRate > 30 },
              ].map((m) => (
                <div key={m.label} className="nf-dash-metric-tile">
                  <span>{m.label}</span>
                  <strong className={m.warn ? 'warn' : ''}>{m.value}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="nf-card nf-dash-panel nf-dash-panel-wide nf-dash-panel-lg">
            <div className="nf-dash-panel-head">
              <Activity size={20} />
              <h2>Recent Activity</h2>
              <Link to="/profiles" className="nf-dash-link">View all profiles →</Link>
            </div>
            {stats.recentActivity.length === 0 ? (
              <p className="nf-dash-empty">No verifications recorded yet.</p>
            ) : (
              <div className="nf-dash-activity">
                {stats.recentActivity.map((row) => (
                  <Link key={row.caseId} to={`/profiles/${row.caseId}`} className={`nf-dash-activity-row ${decisionClass(row.decision)}`}>
                    <span className={`nf-dash-activity-status ${decisionClass(row.decision)}`}>{row.decision}</span>
                    <span className="nf-dash-activity-name">{row.name}</span>
                    <span className="nf-dash-activity-id">{row.caseId}</span>
                    <span className="nf-dash-activity-risk">Risk {row.riskScore}</span>
                    <span className="nf-dash-activity-time">{row.createdAt}</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  )
}

