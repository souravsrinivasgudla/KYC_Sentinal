import { CheckCircle, MinusCircle, SkipForward } from 'lucide-react'
import { AgentStatus } from '../api'

interface Props {
  agents: AgentStatus[]
}

const PHASE_LABELS: Record<string, string> = {
  routing: 'Orchestration',
  intake: 'Intake',
  processing: 'Processing',
  screening: 'Screening',
  risk: 'Risk Analysis',
  decision: 'Decision',
  review: 'Human Review',
  audit: 'Audit',
}

export default function AgentStatusPanel({ agents }: Props) {
  const executed = agents.filter((a) => a.executed).length

  return (
    <div className="card">
      <h3>Agent Execution Status ({executed}/{agents.length} active)</h3>
      <div className="agent-grid">
        {agents.map((agent) => (
          <div key={agent.id} className={`agent-card ${agent.status}`}>
            <div className="agent-card-header">
              {agent.status === 'executed' && <CheckCircle size={14} className="icon-executed" />}
              {agent.status === 'skipped' && <SkipForward size={14} className="icon-skipped" />}
              {agent.status === 'not_run' && <MinusCircle size={14} className="icon-not-run" />}
              <span className="agent-name">{agent.name}</span>
            </div>
            <span className="agent-phase">{PHASE_LABELS[agent.phase] || agent.phase}</span>
            <p className="agent-desc">{agent.description}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
