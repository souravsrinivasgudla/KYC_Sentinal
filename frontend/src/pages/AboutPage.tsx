import { Link } from 'react-router-dom'
import {
  Shield,
  Brain,
  FileSearch,
  Users,
  BarChart3,
  GitBranch,
  CheckCircle,
  AlertTriangle,
  Sparkles,
  Cpu,
  Database,
  Scale,
} from 'lucide-react'

const AGENTS = [
  { phase: 'Intake', items: ['Customer Intake', 'Document Extraction', 'Groq Verification'] },
  { phase: 'Processing', items: ['Profile Normalization'] },
  { phase: 'Verification', items: ['Indian Document Verification (Vision + XGBoost + QR)'] },
  { phase: 'Screening', items: ['Entity Resolution', 'Compliance Screening', 'Adverse Media', 'Evidence Validation'] },
  { phase: 'Risk & Decision', items: ['Financial Profiling', 'Risk Scoring', 'Explainability', 'Decision'] },
  { phase: 'Review & Audit', items: ['Human Review', 'Audit Report'] },
]

const FEATURES = [
  {
    icon: FileSearch,
    title: 'Indian KYC document verification',
    body: 'Upload Aadhaar, PAN, Passport, Voter ID, or Driving Licence. Groq Vision reads document images, OpenCV decodes QR codes when needed, and XGBoost classifiers validate document type and structural integrity.',
  },
  {
    icon: Brain,
    title: 'Multi-agent investigation pipeline',
    body: 'A custom orchestrator routes each case through specialized agents — intake, screening, risk scoring, explainability, and audit — with a full workflow trail you can inspect step by step.',
  },
  {
    icon: Shield,
    title: 'Sanctions, PEP & adverse media',
    body: 'Vector search and RapidFuzz fuzzy matching screen customers against sanctions watchlists, politically exposed persons (PEP), and adverse media corpora sourced from OpenSanctions and optional Kaggle datasets.',
  },
  {
    icon: Scale,
    title: 'Explainable risk scoring',
    body: 'Rule-based and ML signals aggregate into a 0–100 risk score with a transparent breakdown. Decisions map to APPROVE (0–39), REVIEW (40–69), or ESCALATE (70+), each backed by plain-English reasoning from Groq.',
  },
  {
    icon: Users,
    title: 'Human-in-the-loop review',
    body: 'Compliance analysts can approve, reject, or escalate cases from the Profiles view. Overrides are recorded in the audit trail alongside automated agent outputs.',
  },
  {
    icon: BarChart3,
    title: 'Live compliance dashboard',
    body: 'Track acceptance and rejection rates, decision distribution, risk histograms, and recent activity across all verifications with auto-refreshing analytics.',
  },
]

const DOC_TYPES = ['Aadhaar Card', 'PAN Card', 'Passport', 'Voter ID', 'Driving Licence']

const API_ENDPOINTS = [
  { method: 'GET', path: '/api/health', desc: 'Health check and Groq connectivity' },
  { method: 'GET', path: '/api/customers', desc: 'Sample demo customers' },
  { method: 'POST', path: '/api/kyc/run', desc: 'Run full KYC workflow (custom profile)' },
  { method: 'GET', path: '/api/cases', desc: 'List all stored cases' },
  { method: 'GET', path: '/api/cases/{id}', desc: 'Case detail with full agent output' },
  { method: 'POST', path: '/api/cases/{id}/review', desc: 'Submit human review decision' },
  { method: 'GET', path: '/api/cases/{id}/audit', desc: 'Downloadable audit report' },
]

export default function AboutPage() {
  return (
    <>
      <section className="nf-hero nf-hero-compact">
        <div className="nf-hero-content">
          <h1>About <span>KYC Sentinel</span></h1>
          <p>
            Agentic AI compliance platform for Know Your Customer (KYC) due diligence —
            built for the AMD Agentic AI Hackathon 2026 with explainable decisions,
            document intelligence, and auditable workflows.
          </p>
        </div>
      </section>

      <main className="nf-main nf-about">
        <section className="nf-about-section">
          <h2 className="nf-about-heading">
            <Shield size={22} />
            What is KYC Sentinel?
          </h2>
          <p className="nf-about-lead">
            KYC Sentinel automates customer onboarding compliance for financial institutions and
            fintechs. It combines large-language-model document understanding, classical ML
            classifiers, vector search, and a fleet of cooperating agents to produce a defensible
            APPROVE, REVIEW, or ESCALATE recommendation — never a black box.
          </p>
          <div className="nf-about-flow">
            <span>Customer input</span>
            <span className="nf-about-flow-arrow">→</span>
            <span>Orchestrator</span>
            <span className="nf-about-flow-arrow">→</span>
            <span>Specialized agents</span>
            <span className="nf-about-flow-arrow">→</span>
            <span>Risk scoring</span>
            <span className="nf-about-flow-arrow">→</span>
            <span>Decision</span>
            <span className="nf-about-flow-arrow">→</span>
            <span>Human review</span>
            <span className="nf-about-flow-arrow">→</span>
            <span>Audit report</span>
          </div>
        </section>

        <section className="nf-about-section">
          <h2 className="nf-about-heading">
            <Sparkles size={22} />
            Core features
          </h2>
          <div className="nf-about-grid">
            {FEATURES.map((f) => (
              <article key={f.title} className="nf-about-card">
                <f.icon size={26} className="nf-about-card-icon" />
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="nf-about-section">
          <h2 className="nf-about-heading">
            <FileSearch size={22} />
            Supported identity documents
          </h2>
          <p className="nf-about-lead">
            The intake form and Indian Document Verification Agent accept the following
            government-issued proofs. Declared document type, ID number, and name are
            cross-checked against fields extracted from uploaded files.
          </p>
          <ul className="nf-about-tags">
            {DOC_TYPES.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
          <p className="nf-about-note">
            Driving licences use DL No matching; Aadhaar QR payloads are decoded when present;
            name and ID mismatches surface as review flags rather than silent passes.
          </p>
        </section>

        <section className="nf-about-section">
          <h2 className="nf-about-heading">
            <GitBranch size={22} />
            Agent pipeline
          </h2>
          <p className="nf-about-lead">
            Every KYC run executes a dynamic investigation path. The orchestrator invokes
            agents in sequence; skipped agents are noted when not applicable (e.g. no documents uploaded).
          </p>
          <div className="nf-about-agents">
            {AGENTS.map((group) => (
              <div key={group.phase} className="nf-about-agent-group">
                <h4>{group.phase}</h4>
                <ul>
                  {group.items.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className="nf-about-section nf-about-two-col">
          <div>
            <h2 className="nf-about-heading">
              <CheckCircle size={22} />
              Decision thresholds
            </h2>
            <ul className="nf-about-list">
              <li><strong>APPROVE</strong> — Risk score 0–39; low risk, auto-approved when no critical flags.</li>
              <li><strong>REVIEW</strong> — Risk score 40–69; borderline cases need analyst attention.</li>
              <li><strong>ESCALATE</strong> — Risk score 70+; high risk, sanctions hits, or document rejection.</li>
            </ul>
            <p className="nf-about-note">
              ID number or name mismatches against the uploaded document prevent auto-approval
              even when the base score is low.
            </p>
          </div>
          <div>
            <h2 className="nf-about-heading">
              <AlertTriangle size={22} />
              Demo scenarios
            </h2>
            <ul className="nf-about-list">
              <li><strong>Low risk</strong> — e.g. Emily Chen / James Wilson → expected APPROVE.</li>
              <li><strong>Medium risk</strong> — e.g. Marco Silva / Viktor Petrov → expected REVIEW.</li>
              <li><strong>High risk</strong> — e.g. Ahmad Al-Rashid / Kim Jong-un → expected ESCALATE.</li>
            </ul>
          </div>
        </section>

        <section className="nf-about-section">
          <h2 className="nf-about-heading">
            <BarChart3 size={22} />
            Application pages
          </h2>
          <div className="nf-about-pages">
            <Link to="/" className="nf-about-page-link">
              <strong>Home</strong>
              <span>Submit custom KYC requests, upload documents, and watch the live agent pipeline.</span>
            </Link>
            <Link to="/profiles" className="nf-about-page-link">
              <strong>Profiles</strong>
              <span>Browse approved, in-review, and escalated cases; open detail views and human review.</span>
            </Link>
            <Link to="/dashboard" className="nf-about-page-link">
              <strong>Dashboard</strong>
              <span>Live KPIs, decision donut chart, risk histogram, and recent activity.</span>
            </Link>
          </div>
        </section>

        <section className="nf-about-section nf-about-two-col">
          <div>
            <h2 className="nf-about-heading">
              <Cpu size={22} />
              Technology stack
            </h2>
            <ul className="nf-about-list">
              <li><strong>Frontend</strong> — React, Vite, TypeScript, React Router</li>
              <li><strong>Backend</strong> — FastAPI, Python, SQLite case store</li>
              <li><strong>AI / ML</strong> — Groq Vision & chat, XGBoost document classifiers, TF-IDF vector store</li>
              <li><strong>Matching</strong> — RapidFuzz, OpenCV QR decode, HuggingFace TrOCR fallback</li>
              <li><strong>State</strong> — LangGraph-compatible KYC state across agents</li>
            </ul>
          </div>
          <div>
            <h2 className="nf-about-heading">
              <Database size={22} />
              Data sources
            </h2>
            <ul className="nf-about-list">
              <li>OpenSanctions — consolidated sanctions & PEP lists</li>
              <li>Country & occupation risk reference tables</li>
              <li>Optional Kaggle synthetic KYC / AML datasets</li>
              <li>Refresh via <code>python -m scripts.fetch_datasets</code></li>
            </ul>
          </div>
        </section>

        <section className="nf-about-section">
          <h2 className="nf-about-heading">REST API</h2>
          <p className="nf-about-lead">
            The FastAPI backend exposes the following endpoints (default base URL{' '}
            <code>http://localhost:8000</code>):
          </p>
          <div className="nf-about-api-table-wrap">
            <table className="nf-about-api-table">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Endpoint</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {API_ENDPOINTS.map((row) => (
                  <tr key={row.path}>
                    <td><span className={`nf-about-method nf-about-method-${row.method.toLowerCase()}`}>{row.method}</span></td>
                    <td><code>{row.path}</code></td>
                    <td>{row.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="nf-about-section nf-about-amd">
          <h2 className="nf-about-heading">AMD alignment</h2>
          <p className="nf-about-lead">
            KYC Sentinel is designed for AMD infrastructure: vector search layers can run on
            ROCm-accelerated embedding models; lightweight screening models target Ryzen AI edge
            deployment; multi-agent orchestration demonstrates agentic AI workloads on AMD hardware.
          </p>
        </section>
      </main>
    </>
  )
}
