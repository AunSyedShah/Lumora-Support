import { useParams } from 'react-router-dom'

import { FULL_ACCESS_ROLES, useAuth } from '../../auth/context'
import { Badge, Card, ErrorNotice, Loading, SectionTitle } from '../../components/ui'
import { timeAgo } from '../../lib/format'
import { PRIORITY, PRIORITY_TONE, reviewReasons } from '../../lib/labels'
import { slaLine } from '../../lib/sla'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'
import Conversation, { FactTiles } from './workspace/Conversation'
import { Actions, Notes, PolicyCheck, Suggestion, Timeline } from './workspace/Panels'
import ReplyBox from './workspace/ReplyBox'
import ReviewPanel from './workspace/ReviewPanel'

const REVIEW_OPEN = ['pending', 'rejected']

export default function ComplaintWorkspace() {
  const { complaintId } = useParams()
  const { user } = useAuth()
  const { subcategoryName, departmentName } = useTaxonomy()
  const complaint = useApi(`/complaints/${complaintId}`)
  const work = useApi(`/workflow/complaints/${complaintId}`)
  const notes = useApi(`/workflow/complaints/${complaintId}/notes`)
  const audit = useApi(`/workflow/complaints/${complaintId}/audit`)

  const reloadAll = () => {
    complaint.reload()
    work.reload()
    notes.reload()
    audit.reload()
  }

  if ((complaint.loading && !complaint.data) || (work.loading && !work.data)) return <Loading />
  const error = complaint.error || work.error
  if (error) return <ErrorNotice message={error} onRetry={reloadAll} />

  const c = complaint.data
  const w = work.data
  const sla = slaLine(w.sla)
  const inReview = REVIEW_OPEN.includes(w.review_status)
  const isReviewer = FULL_ACCESS_ROLES.includes(user.role)

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex max-w-3xl flex-col gap-1.5">
          <p className="m-0 text-[15px] text-muted">
            {[c.complaint_id, subcategoryName(c.subcategory), departmentName(c.department_code), `opened ${timeAgo(c.created_at)}`].filter(Boolean).join(' · ')}
          </p>
          <h1 className="m-0 font-display text-[32px] leading-tight font-bold tracking-tight">{c.title}</h1>
          {c.resolution?.summary && <p className="m-0 text-[15px] text-muted">In short: {c.resolution.summary}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {sla && <Badge tone={sla.tone === 'green' ? 'sun' : sla.tone}>{sla.text}</Badge>}
          <Badge tone={PRIORITY_TONE[c.priority] || 'outline'}>{PRIORITY[c.priority] || 'Not set'} priority</Badge>
        </div>
      </div>

      {inReview &&
        (isReviewer ? (
          <ReviewPanel complaint={c} work={w} onDone={reloadAll} />
        ) : (
          <div className="flex flex-col gap-1 rounded-2xl bg-sun-soft px-5 py-4 text-sun-ink">
            <strong>A reviewer is taking a second look before this goes out.</strong>
            <span>{reviewReasons(w.review_reasons).join(' · ')}</span>
          </div>
        ))}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card className="flex min-w-0 flex-col gap-6">
          <Conversation complaint={c} />
          <div className="flex flex-col gap-3">
            <SectionTitle className="text-lg">Order and history</SectionTitle>
            <FactTiles complaint={c} />
          </div>
          <ReplyBox key={`${c.complaint_id}-${c.response_sent_at}`} complaint={c} blocked={inReview} onSent={reloadAll} />
        </Card>

        <aside aria-label="Suggested handling" className="flex flex-col gap-5">
          <Suggestion resolution={c.resolution} />
          <PolicyCheck resolution={c.resolution} />
          <Actions complaint={c} work={w} onDone={reloadAll} />
          <Notes complaintId={c.complaint_id} notes={notes.data} onAdded={notes.reload} />
          <Timeline events={audit.data} />
        </aside>
      </div>
    </div>
  )
}
