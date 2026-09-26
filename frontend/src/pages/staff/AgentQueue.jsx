import { useAuth } from '../../auth/context'
import WorkCard from '../../components/WorkCard'
import { EmptyState, ErrorNotice, Loading, PageTitle } from '../../components/ui'
import { useApi } from '../../lib/useApi'

function Tile({ label, value, highlight }) {
  return (
    <div className={`flex flex-col gap-1 rounded-[22px] px-5 py-4 ${highlight && value > 0 ? 'bg-sun-soft text-sun-ink' : 'bg-white'}`}>
      <span className="text-sm text-muted">{label}</span>
      <span className="font-display text-[32px] leading-none font-bold">{value}</span>
    </div>
  )
}

export default function AgentQueue() {
  const { user } = useAuth()
  const dashboard = useApi('/dashboard/agent')
  if (dashboard.loading && !dashboard.data) return <Loading />
  if (dashboard.error) return <ErrorNotice message={dashboard.error} onRetry={dashboard.reload} />
  const d = dashboard.data
  const firstName = user.first_name || user.username

  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        eyebrow={d.open_assigned ? `Hi ${firstName} — ${d.open_assigned} ${d.open_assigned === 1 ? 'person is' : 'people are'} waiting on you.` : `Hi ${firstName}`}
        title="My queue"
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="Open" value={d.open_assigned} />
        <Tile label="Running out of time" value={d.sla_at_risk} highlight />
        <Tile label="Overdue" value={d.sla_breached} highlight />
        <Tile label="Follow-ups due" value={d.follow_ups_due} highlight />
      </div>
      {d.complaints.length === 0 ? (
        <EmptyState title="Nothing waiting for you">New complaints are assigned to you automatically when they come in.</EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {d.complaints.map((c) => (
            <WorkCard key={c.complaint_id} item={c} to={`/work/complaints/${c.complaint_id}`}>
              {c.escalation_warning && <span className="font-semibold text-rust">Escalated</span>}
              {c.validation.review_status === 'pending' && <span className="text-muted">Waiting for a second look</span>}
            </WorkCard>
          ))}
        </div>
      )}
    </div>
  )
}
