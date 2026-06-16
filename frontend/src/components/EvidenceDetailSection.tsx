import { CheckCircle, XCircle, AlertTriangle, FileSearch, ShieldCheck } from 'lucide-react'
import { KYCResult } from '../api'
import { buildEvidenceSummary } from '../utils/evidenceDetails'

function StatusIcon({ ok }: { ok: boolean }) {
  return ok
    ? <CheckCircle size={16} style={{ color: 'var(--nf-success)', flexShrink: 0 }} />
    : <XCircle size={16} style={{ color: 'var(--nf-red)', flexShrink: 0 }} />
}

function verdictClass(verdict: string) {
  if (verdict === 'VERIFIED') return 'verified'
  if (verdict === 'REJECTED') return 'rejected'
  if (verdict === 'NEEDS_REVIEW') return 'needs_review'
  return 'pending'
}

export default function EvidenceDetailSection({ result }: { result: KYCResult }) {
  const evidence = buildEvidenceSummary(result)

  if (!evidence.hasEvidence) {
    return (
      <div className="nf-card">
        <h3><FileSearch size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: -2 }} />Evidence &amp; Validation</h3>
        <p style={{ fontSize: '0.9rem', color: 'var(--nf-dim)', marginTop: '0.5rem' }}>
          No evidence documents were uploaded for this profile.
        </p>
      </div>
    )
  }

  const satisfied = evidence.checks.filter((c) => c.satisfied)
  const unsatisfied = evidence.checks.filter((c) => !c.satisfied)

  return (
    <div className="nf-card nf-evidence-section">
      <h3><ShieldCheck size={16} style={{ display: 'inline', marginRight: 6, verticalAlign: -2 }} />Evidence &amp; Validation</h3>

      {evidence.summary && (
        <p className="nf-evidence-summary">{evidence.summary}</p>
      )}

      <div className="nf-evidence-stats">
        {[
          { label: 'Total Docs', value: evidence.stats.totalDocs, color: 'var(--nf-text)' },
          { label: 'Verified', value: evidence.stats.verified, color: 'var(--nf-success)' },
          { label: 'Rejected', value: evidence.stats.rejected, color: 'var(--nf-red)' },
          { label: 'In Review', value: evidence.stats.review, color: 'var(--nf-warning)' },
          {
            label: 'Confidence',
            value: evidence.overallConfidence != null ? `${Math.round(evidence.overallConfidence * 100)}%` : '—',
            color: 'var(--nf-muted)',
          },
        ].map((s) => (
          <div key={s.label} className="nf-evidence-stat">
            <div className="nf-evidence-stat-label">{s.label}</div>
            <div className="nf-evidence-stat-value" style={{ color: s.color }}>{s.value}</div>
          </div>
        ))}
      </div>

      <div className="nf-evidence-pipeline">
        <span className={`nf-evidence-pill ${evidence.mlPassed ? 'pass' : 'fail'}`}>
          ML Validation: {evidence.mlPassed ? 'Passed' : 'Failed'}
        </span>
        <span className={`nf-evidence-pill ${evidence.groqPassed ? 'pass' : 'fail'}`}>
          Groq Semantic: {evidence.groqPassed ? 'Passed' : 'Failed'}
        </span>
        <span className={`nf-evidence-pill ${evidence.validationPassed ? 'pass' : 'fail'}`}>
          Combined: {evidence.validationPassed ? 'Passed' : 'Failed'}
        </span>
        {evidence.recommendation && (
          <span className="nf-evidence-pill neutral">
            Recommendation: {evidence.recommendation}
          </span>
        )}
      </div>

      <div className="nf-evidence-checklists">
        <div className="nf-evidence-checklist satisfied">
          <h4><CheckCircle size={14} /> Satisfied ({satisfied.length})</h4>
          {satisfied.length === 0 ? (
            <p className="nf-evidence-empty">No requirements satisfied yet.</p>
          ) : (
            <ul>
              {satisfied.map((c) => (
                <li key={c.id}>
                  <StatusIcon ok />
                  <div>
                    <strong>{c.label}</strong>
                    {c.detail && <span>{c.detail}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="nf-evidence-checklist unsatisfied">
          <h4><XCircle size={14} /> Not Satisfied ({unsatisfied.length})</h4>
          {unsatisfied.length === 0 ? (
            <p className="nf-evidence-empty">All evidence requirements met.</p>
          ) : (
            <ul>
              {unsatisfied.map((c) => (
                <li key={c.id}>
                  <StatusIcon ok={false} />
                  <div>
                    <strong>{c.label}</strong>
                    {c.detail && <span>{c.detail}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {evidence.criticalIssues.length > 0 && (
        <div className="nf-evidence-critical">
          <h4><AlertTriangle size={14} /> Critical Issues</h4>
          <ul>
            {evidence.criticalIssues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        </div>
      )}

      {evidence.documentsReviewed.length > 0 && (
        <div className="nf-evidence-groq-review">
          <h4>Groq Document Review</h4>
          {evidence.documentsReviewed.map((doc, i) => (
            <div key={i} className="nf-evidence-groq-doc">
              <div className="nf-evidence-groq-doc-header">
                <span>{doc.filename}</span>
                <span className="nf-evidence-groq-type">{doc.docType}</span>
                <span>Authenticity: {Math.round(doc.authenticityScore * 100)}%</span>
              </div>
              <div className="nf-evidence-groq-flags">
                <span className={doc.matchesProfile ? 'pass' : 'fail'}>
                  {doc.matchesProfile ? '✓' : '✗'} Profile match
                </span>
                <span className={doc.idNumberMatches ? 'pass' : 'fail'}>
                  {doc.idNumberMatches ? '✓' : '✗'} ID number match
                </span>
              </div>
              {doc.issues.length > 0 && (
                <ul className="nf-evidence-groq-issues">
                  {doc.issues.map((issue, j) => (
                    <li key={j}>{issue}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="nf-evidence-documents">
        <h4>Per-Document Evidence</h4>
        {evidence.documents.map((doc) => (
          <div key={doc.evidenceId || doc.filename} className={`nf-evidence-doc-card ${verdictClass(doc.verdict)}`}>
            <div className="nf-evidence-doc-header">
              <div>
                <span className="nf-evidence-doc-type">{doc.docTypeDisplay}</span>
                <span className="nf-evidence-doc-file">{doc.filename}</span>
                {doc.docNumber && <span className="nf-evidence-doc-num">#{doc.docNumber}</span>}
              </div>
              <span className={`nf-profile-doc-verdict ${verdictClass(doc.verdict)}`}>{doc.verdict}</span>
            </div>

            {doc.verdictReason && (
              <p className="nf-evidence-doc-reason">{doc.verdictReason}</p>
            )}

            <div className="nf-evidence-doc-scores">
              <span>Completeness: {Math.round(doc.completeness * 100)}%</span>
              <span>Trust: {Math.round(doc.trustSignal * 100)}%</span>
              <span>Validity: {Math.round(doc.validityConfidence * 100)}%</span>
              {doc.groqIntegrityScore != null && (
                <span>Groq integrity: {Math.round(doc.groqIntegrityScore * 100)}%</span>
              )}
            </div>

            <div className="nf-evidence-doc-checks">
              {doc.satisfiedChecks.length > 0 && (
                <div className="nf-evidence-doc-satisfied">
                  <strong>Satisfied</strong>
                  <ul>
                    {doc.satisfiedChecks.map((c, i) => (
                      <li key={i}><CheckCircle size={12} /> {c}</li>
                    ))}
                  </ul>
                </div>
              )}
              {doc.unsatisfiedChecks.length > 0 && (
                <div className="nf-evidence-doc-unsatisfied">
                  <strong>Not satisfied</strong>
                  <ul>
                    {doc.unsatisfiedChecks.map((c, i) => (
                      <li key={i}><XCircle size={12} /> {c}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {Object.keys(doc.extractedFields).length > 0 && (
              <details className="nf-evidence-extracted">
                <summary>Groq extracted fields</summary>
                <div className="nf-groq-fields-grid">
                  {Object.entries(doc.extractedFields).map(([key, val]) => (
                    <div key={key} className="nf-groq-field-row">
                      <span className="nf-groq-field-key">{key.replace(/_/g, ' ')}</span>
                      <span className="nf-groq-field-val">
                        {typeof val === 'boolean' ? (val ? 'Yes' : 'No') : String(val)}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}

            {doc.groqNotes && (
              <p className="nf-evidence-groq-note">{doc.groqNotes}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
