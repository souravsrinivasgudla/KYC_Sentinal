import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { User, Calendar, AlertTriangle } from 'lucide-react'
import { StoredCase } from '../api'
import HumanReviewPanel from '../components/HumanReviewPanel'
import { decisionClass, decisionLabel, effectiveDecision, needsHumanReview } from '../utils/decision'

type ProfileTab = 'APPROVE' | 'REVIEW' | 'ESCALATE'

const TABS: { key: ProfileTab; label: string }[] = [
  { key: 'APPROVE', label: 'Approved' },
  { key: 'REVIEW', label: 'In Review' },
  { key: 'ESCALATE', label: 'Escalated' },
]

interface Props {
  cases: StoredCase[]
  onRefresh: () => void
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

function ProfileCardBody({ c, status }: { c: StoredCase; status: ReturnType<typeof effectiveDecision> }) {
  return (
    <>
      <div className="nf-profile-card-top">
        <span className={`nf-profile-status ${decisionClass(status)}`}>
          {decisionLabel(status)}
        </span>
        <span className="nf-profile-score">{c.risk_score}</span>
      </div>
      <div className="nf-profile-card-body">
        <div className="nf-profile-card-name">{c.customer_name}</div>
        <div className="nf-profile-card-meta">
          <span>{c.case_id}</span>
          <span className="nf-profile-card-date">
            <Calendar size={12} />
            {formatDate(c.created_at)}
          </span>
        </div>
        {c.missing_fields?.length > 0 && (
          <div className="nf-profile-card-warn">
            <AlertTriangle size={12} />
            {c.missing_fields.length} missing field{c.missing_fields.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </>
  )
}

export default function ProfilesPage({ cases, onRefresh }: Props) {
  const [activeTab, setActiveTab] = useState<ProfileTab>('APPROVE')

  const grouped = useMemo(() => {
    const buckets: Record<ProfileTab, StoredCase[]> = {
      APPROVE: [],
      REVIEW: [],
      ESCALATE: [],
    }
    for (const c of cases) {
      buckets[effectiveDecision(c)].push(c)
    }
    return buckets
  }, [cases])

  const visible = grouped[activeTab]

  return (
    <>
      <section className="nf-hero nf-hero-compact">
        <div className="nf-hero-content">
          <h1>Customer <span>Profiles</span></h1>
          <p>All verifications grouped by compliance decision — approved, in review, or escalated.</p>
        </div>
      </section>

      <main className="nf-main">
        <div className="nf-profiles-tabs">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`nf-profile-tab ${activeTab === key ? 'active' : ''} ${decisionClass(key)}`}
              onClick={() => setActiveTab(key)}
            >
              {label}
              <span className="nf-profile-tab-count">{grouped[key].length}</span>
            </button>
          ))}
        </div>

        {activeTab === 'REVIEW' && visible.some(needsHumanReview) && (
          <p className="nf-profiles-review-hint">
            Profiles awaiting officer decision can be approved, overridden, or escalated directly from each card.
          </p>
        )}

        {visible.length === 0 ? (
          <div className="nf-card nf-empty nf-profiles-empty">
            <User size={40} style={{ opacity: 0.2, margin: '0 auto 1rem' }} />
            <p>No {decisionLabel(activeTab).toLowerCase()} profiles yet.</p>
          </div>
        ) : (
          <div className="nf-profiles-grid">
            {visible.map((c) => {
              const status = effectiveDecision(c)
              const showReview = activeTab === 'REVIEW' && needsHumanReview(c)

              if (showReview) {
                return (
                  <div
                    key={c.case_id}
                    className={`nf-profile-card nf-profile-card-reviewable ${decisionClass(status)}`}
                  >
                    <Link to={`/profiles/${c.case_id}`} className="nf-profile-card-link">
                      <ProfileCardBody c={c} status={status} />
                    </Link>
                    <HumanReviewPanel
                      caseId={c.case_id}
                      compact
                      onComplete={() => onRefresh()}
                    />
                  </div>
                )
              }

              return (
                <Link
                  key={c.case_id}
                  to={`/profiles/${c.case_id}`}
                  className={`nf-profile-card ${decisionClass(status)}`}
                >
                  <ProfileCardBody c={c} status={status} />
                </Link>
              )
            })}
          </div>
        )}
      </main>
    </>
  )
}
