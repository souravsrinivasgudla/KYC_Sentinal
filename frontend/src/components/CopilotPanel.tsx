import { useRef, useState } from 'react'
import { Send, Sparkles, User } from 'lucide-react'
import { KYCResult, askCopilot } from '../api'
import { confidenceBand, confidenceLabel, confidencePct, hasConfidence } from '../utils/confidence'
import { consistencyBand, consistencyLabel } from '../utils/consistency'

interface Props {
  caseId: string
  result: KYCResult
}

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const SUGGESTED = [
  'Why was this customer escalated?',
  'What caused the risk score?',
  'Why did EDD trigger?',
  'What consistency issues were found?',
  'Summarize this case.',
]

export default function CopilotPanel({ caseId, result }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  const decision = result.decision.final_status || result.decision.status
  const confBand = confidenceBand(result.overall_confidence)
  const consBand = consistencyBand(result.consistency_score)

  const ask = async (question: string) => {
    const q = question.trim()
    if (!q || loading) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: q }])
    setLoading(true)
    try {
      const res = await askCopilot(caseId, q)
      setMessages((prev) => [...prev, { role: 'assistant', content: res.answer }])
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Sorry — the copilot request failed. Please try again.' }])
    } finally {
      setLoading(false)
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    }
  }

  return (
    <div className="nf-copilot">
      {/* Executive Case Summary (Part 13) */}
      <div className="nf-copilot-summary">
        <div className="nf-copilot-summary-title">Executive Case Summary</div>
        <div className="nf-copilot-summary-grid">
          <div>
            <span className="nf-copilot-k">Decision</span>
            <span className="nf-copilot-v">{decision}</span>
          </div>
          <div>
            <span className="nf-copilot-k">Risk Score</span>
            <span className="nf-copilot-v">{result.risk_assessment?.risk_score ?? '—'}</span>
          </div>
          {hasConfidence(result.overall_confidence) && (
            <div>
              <span className="nf-copilot-k">Confidence</span>
              <span className="nf-copilot-v">{confidencePct(result.overall_confidence)}% · {confidenceLabel(confBand)}</span>
            </div>
          )}
          <div>
            <span className="nf-copilot-k">EDD</span>
            <span className="nf-copilot-v">{result.edd_triggered ? 'Triggered' : 'Not triggered'}</span>
          </div>
          {result.consistency_summary && (
            <div>
              <span className="nf-copilot-k">Consistency</span>
              <span className="nf-copilot-v">{consistencyLabel(consBand)}</span>
            </div>
          )}
        </div>
        {(result.top_risk_drivers?.length ?? 0) > 0 && (
          <div className="nf-copilot-drivers">
            <span className="nf-copilot-k">Top Risk Drivers</span>
            <ul>{result.top_risk_drivers!.map((d, i) => <li key={i}>{d.factor}</li>)}</ul>
          </div>
        )}
        {result.executive_summary && <p className="nf-copilot-exec">{result.executive_summary}</p>}
      </div>

      {/* Conversation */}
      <div className="nf-copilot-chat">
        {messages.length === 0 && (
          <div className="nf-copilot-empty">
            <Sparkles size={32} style={{ opacity: 0.3 }} />
            <p>Ask a question about this case. The copilot answers using only this case's evidence.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`nf-copilot-msg ${m.role}`}>
            <div className="nf-copilot-msg-icon">
              {m.role === 'user' ? <User size={14} /> : <Sparkles size={14} />}
            </div>
            <div className="nf-copilot-msg-body">{m.content}</div>
          </div>
        ))}
        {loading && (
          <div className="nf-copilot-msg assistant">
            <div className="nf-copilot-msg-icon"><Sparkles size={14} /></div>
            <div className="nf-copilot-msg-body" style={{ opacity: 0.6 }}>Thinking…</div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Suggested questions (Part 9) */}
      <div className="nf-copilot-suggested">
        {SUGGESTED.map((q) => (
          <button key={q} type="button" className="nf-copilot-chip" onClick={() => ask(q)} disabled={loading}>
            {q}
          </button>
        ))}
      </div>

      {/* Input (Part 8) */}
      <form className="nf-copilot-input" onSubmit={(e) => { e.preventDefault(); ask(input) }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this case…"
          disabled={loading}
        />
        <button type="submit" className="nf-copilot-send" disabled={loading || !input.trim()}>
          <Send size={16} />
        </button>
      </form>
    </div>
  )
}
