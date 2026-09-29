import { Link, useLocation, useParams } from 'react-router-dom'

import { Badge, Button, EmptyState, ErrorNotice, Loading } from '../../components/ui'
import { timeAgo } from '../../lib/format'
import { CUSTOMER_STATUS, CUSTOMER_STATUS_TONE } from '../../lib/labels'
import { useApi } from '../../lib/useApi'
import ComplaintConversation from './ComplaintConversation'

function ComplaintCard({ complaint, selected }) {
  return (
    <Link
      to={`/my/complaints/${complaint.complaint_id}`}
      aria-current={selected ? 'page' : undefined}
      className={`flex flex-col gap-2 rounded-[20px] bg-white px-5 py-4 text-ink no-underline ${selected ? 'outline-2 outline-forest' : 'hover:bg-sand'}`}
    >
      <span className="text-[17px] font-semibold">{complaint.title}</span>
      <span className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={CUSTOMER_STATUS_TONE[complaint.status] || 'green'}>{CUSTOMER_STATUS[complaint.status] || complaint.resolution_status}</Badge>
        {complaint.last_message_from === 'lumora' && !['resolved', 'closed'].includes(complaint.status) && <Badge tone="sun">New message</Badge>}
        <span className="text-muted">
          {complaint.complaint_id} · {timeAgo(complaint.created_at)}
        </span>
      </span>
    </Link>
  )
}

export default function MyComplaints() {
  const { complaintId } = useParams()
  const location = useLocation()
  const list = useApi('/complaints/my')
  const complaints = list.data || []
  const selectedId = complaintId || complaints[0]?.complaint_id

  if (list.loading && !list.data) return <Loading />
  if (list.error) return <ErrorNotice message={list.error} onRetry={list.reload} />

  if (complaints.length === 0) {
    return (
      <div className="mx-auto flex max-w-xl flex-col items-center gap-6 py-10">
        <EmptyState title="No complaints yet">When something isn’t right with a Lumora device, order or subscription, tell us here.</EmptyState>
        <Button to="/my/complaints/new">Tell us what happened</Button>
      </div>
    )
  }

  // On a phone the list and the complaint are separate views; side by side from large screens up.
  return (
    <div className="grid grid-cols-1 gap-7 lg:grid-cols-[380px_minmax(0,1fr)]">
      <section aria-label="Your complaints" className={`flex-col gap-3 ${complaintId ? 'hidden lg:flex' : 'flex'}`}>
        <h1 className="m-0 mb-1 font-display text-[30px] font-bold tracking-tight">My complaints</h1>
        {complaints.map((c) => (
          <ComplaintCard key={c.complaint_id} complaint={c} selected={c.complaint_id === selectedId} />
        ))}
      </section>
      {selectedId && (
        <div className={`flex min-w-0 flex-col gap-3 ${complaintId ? '' : 'hidden lg:flex'}`}>
          <Link to="/my/complaints" className="text-[15px] font-semibold text-forest lg:hidden">
            ← All my complaints
          </Link>
          <ComplaintConversation
            key={selectedId}
            complaintId={selectedId}
            justSent={location.state?.justSent && location.pathname.endsWith(selectedId)}
            notes={location.state?.notes || []}
            onChange={list.reload}
          />
        </div>
      )}
    </div>
  )
}
