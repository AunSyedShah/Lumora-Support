import { useState } from 'react'

import { useAuth } from '../../auth/context'
import WorkCard from '../../components/WorkCard'
import { Badge, EmptyState, ErrorNotice, Loading, PageTitle } from '../../components/ui'
import { isPast } from '../../lib/format'
import { ESCALATION } from '../../lib/labels'
import { useApi } from '../../lib/useApi'

const WAITING_FOR_REVIEW = ['pending', 'rejected']

// Each tile is also a filter for the list below.
const SHOW = {
  all: () => true,
  at_risk: (c) => c.next_deadline?.state === 'at_risk',
  overdue: (c) => c.next_deadline?.state === 'breached',
  follow_ups: (c) => isPast(c.follow_up_due),
}

function Tile({ label, value, active, warn, onClick }) {
  const tone = active ? 'bg-forest text-white' : warn && value > 0 ? 'bg-sun-soft text-sun-ink hover:bg-sun' : 'bg-white hover:bg-sand'
  return (
    <button type="button" onClick={onClick} aria-pressed={active} className={`flex cursor-pointer flex-col gap-1 rounded-[22px] border-0 px-5 py-4 text-left ${tone}`}>
      <span className={`text-sm ${active ? 'text-white/80' : 'text-muted'}`}>{label}</span>
      <span className="font-display text-[32px] leading-none font-bold">{value}</span>
    </button>
  )
}

function Group({ title, note, items, startHere }) {
  if (!items.length) return null
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 className="m-0 font-display text-xl font-bold">
          {title} <span className="font-sans text-base font-normal text-muted">({items.length})</span>
        </h2>
        {note && <p className="m-0 text-[15px] text-muted">{note}</p>}
      </div>
      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {items.map((c, index) => (
          <li key={c.complaint_id}>
            <WorkCard item={c} to={`/work/complaints/${c.complaint_id}`}>
              {startHere && index === 0 && <Badge tone="dark">Start here</Badge>}
              {/* The status line already says "Escalated"; here: to whom. */}
              {c.escalation_warning && <span className="font-semibold text-rust">To {(ESCALATION[c.escalation_warning.level] || 'a specialist').toLowerCase()}</span>}
              {isPast(c.follow_up_due) && <span className="font-semibold">Follow-up due</span>}
            </WorkCard>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function AgentQueue() {
  const { user } = useAuth()
  const dashboard = useApi('/dashboard/agent')
  const [show, setShow] = useState('all')
  const [search, setSearch] = useState('')
  if (dashboard.loading && !dashboard.data) return <Loading />
  if (dashboard.error) return <ErrorNotice message={dashboard.error} onRetry={dashboard.reload} />
  const d = dashboard.data
  const firstName = user.first_name || user.username

  const words = search.trim().toLowerCase()
  const shown = d.complaints.filter(SHOW[show]).filter((c) => !words || `${c.complaint_id} ${c.title}`.toLowerCase().includes(words))
  const ready = shown.filter((c) => !WAITING_FOR_REVIEW.includes(c.validation.review_status))
  const waiting = shown.filter((c) => WAITING_FOR_REVIEW.includes(c.validation.review_status))
  const pick = (value) => setShow(show === value ? 'all' : value)

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageTitle
        eyebrow={d.open_assigned ? `Hi ${firstName} — ${d.open_assigned} ${d.open_assigned === 1 ? 'person is' : 'people are'} waiting on you.` : `Hi ${firstName}`}
        title="My queue"
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="Open" value={d.open_assigned} active={show === 'all'} onClick={() => setShow('all')} />
        <Tile label="Running out of time" value={d.sla_at_risk} warn active={show === 'at_risk'} onClick={() => pick('at_risk')} />
        <Tile label="Overdue" value={d.sla_breached} warn active={show === 'overdue'} onClick={() => pick('overdue')} />
        <Tile label="Follow-ups due" value={d.follow_ups_due} warn active={show === 'follow_ups'} onClick={() => pick('follow_ups')} />
      </div>
      {d.complaints.length > 0 && (
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          Find a complaint
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Words from the title or a complaint number"
            className="rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] text-ink focus:border-forest focus:outline-none"
          />
        </label>
      )}
      {d.complaints.length === 0 && <EmptyState title="Nothing waiting for you">New complaints are assigned to you automatically when they come in.</EmptyState>}
      {d.complaints.length > 0 && shown.length === 0 && <EmptyState title="Nothing here">Try another tile or other words.</EmptyState>}
      <Group title="Ready for you" note="Most pressing first." items={ready} startHere={show === 'all' && !words} />
      <Group title="Waiting for a second look" note="A reviewer checks these first — you can reply once they are done." items={waiting} />
    </div>
  )
}
