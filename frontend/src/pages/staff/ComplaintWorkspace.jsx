import { useEffect } from 'react'
import { useLocation, useParams } from 'react-router-dom'

import { FULL_ACCESS_ROLES, useAuth } from '../../auth/context'
import { Badge, Card, ErrorNotice, Loading, SectionTitle, SuccessNotice } from '../../components/ui'
import { timeAgo } from '../../lib/format'
import { PRIORITY, PRIORITY_TONE, SENTIMENT, SENTIMENT_TONE, reviewReasons } from '../../lib/labels'
import { slaLine } from '../../lib/sla'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'
import Conversation, { FactTiles } from './workspace/Conversation'
import { Actions, Notes, PolicyCheck, Suggestion, Timeline } from './workspace/Panels'
import { HandOver, RelatedComplaints } from './workspace/Related'
import ReplyBox from './workspace/ReplyBox'
import ReviewPanel from './workspace/ReviewPanel'

const REVIEW_OPEN = ['pending', 'rejected']

/** The customer's mood (sentiment + tone indicators). Shown for the reply's tone only - priority comes from our rules. */
function Mood({ sentiment, emotions }) {
  if (!sentiment) return null
  const feelings = (emotions || []).map((e) => e.toLowerCase())
  return (
    <Badge tone={SENTIMENT_TONE[sentiment] || 'sand'}>
      <span title="How the customer feels. It shapes the tone of the reply, not the priority.">
        Mood: {SENTIMENT[sentiment] || sentiment}
        {feelings.length > 0 && <span className="font-normal"> · {feelings.join(', ')}</span>}
      </span>
    </Badge>
  )
}

/** Other problems in the same message and the teams that help (SRS Steps 13 and 24). */
function AlsoInvolves({ complaint, names }) {
  const secondary = (complaint.resolution?.secondary_issues || []).map(names.subcategoryName).filter(Boolean)
  const teams = (complaint.supporting_departments || []).filter((d) => d !== complaint.department_code).map(names.departmentName)
  if (!secondary.length && !teams.length) return null
  return (
    <p className="m-0 text-[15px] text-muted">
      {secondary.length > 0 && (
        <>
          <strong className="text-ink">Also about:</strong> {secondary.join(', ')}
        </>
      )}
      {secondary.length > 0 && teams.length > 0 && ' · '}
      {teams.length > 0 && (
        <>
          <strong className="text-ink">Helping teams:</strong> {teams.join(', ')}
        </>
      )}
    </p>
  )
}

export default function ComplaintWorkspace() {
  const { complaintId } = useParams()
  const { state } = useLocation() // { reviewed, left } after a reviewer's decision on the previous complaint
  const { user } = useAuth()
  const names = useTaxonomy()
  const { subcategoryName, departmentName } = names
  const complaint = useApi(`/complaints/${complaintId}`)
  const work = useApi(`/workflow/complaints/${complaintId}`)
  const notes = useApi(`/workflow/complaints/${complaintId}/notes`)
  const audit = useApi(`/workflow/complaints/${complaintId}/audit`)

  // A new complaint (e.g. the next one after a review decision) starts at the top, where its title and notices are.
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [complaintId])

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
      {state?.reviewed && state.reviewed !== c.complaint_id && (
        <SuccessNotice>
          Done with {state.reviewed}. Here’s the next one — {state.left} {state.left === 1 ? 'complaint needs' : 'complaints need'} a second look.
        </SuccessNotice>
      )}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex max-w-3xl flex-col gap-1.5">
          <p className="m-0 text-[15px] text-muted">
            {[c.complaint_id, subcategoryName(c.subcategory), departmentName(c.department_code), `opened ${timeAgo(c.created_at)}`].filter(Boolean).join(' · ')}
          </p>
          <h1 className="m-0 font-display text-[32px] leading-tight font-bold tracking-tight">{c.title}</h1>
          {c.resolution?.summary && <p className="m-0 text-[15px] text-muted">In short: {c.resolution.summary}</p>}
          <AlsoInvolves complaint={c} names={names} />
        </div>
        <div className="flex flex-wrap gap-2">
          {sla && <Badge tone={sla.tone === 'green' ? 'sun' : sla.tone}>{sla.text}</Badge>}
          <Badge tone={PRIORITY_TONE[c.priority] || 'outline'}>{PRIORITY[c.priority] ? `${PRIORITY[c.priority]} priority` : 'Priority not set'}</Badge>
          <Mood sentiment={c.sentiment} emotions={c.emotions} />
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

      {/* Wide screens: conversation left, guidance right. One column: the guidance comes before the
          conversation and reply box, so the plan is read before anything is sent. */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_420px] xl:grid-rows-[auto_1fr]">
        <aside aria-label="Suggested handling" className="flex flex-col gap-5 xl:col-start-2 xl:row-start-1">
          <Suggestion resolution={c.resolution} />
          <PolicyCheck resolution={c.resolution} score={c.verification_score} />
        </aside>

        <Card className="flex min-w-0 flex-col gap-6 self-start xl:col-start-1 xl:row-span-2 xl:row-start-1">
          <Conversation complaint={c} />
          <ReplyBox key={`${c.complaint_id}-${c.response_sent_at}`} complaint={c} blocked={inReview} onSent={reloadAll} />
          <div className="flex flex-col gap-3">
            <SectionTitle className="text-lg">Order and history</SectionTitle>
            <FactTiles complaint={c} />
          </div>
        </Card>

        <aside aria-label="Status and history" className="flex flex-col gap-5 xl:col-start-2 xl:row-start-2">
          <Actions complaint={c} work={w} canEscalate={isReviewer} inReview={inReview} onDone={reloadAll} />
          {isReviewer && <HandOver complaint={c} work={w} onDone={reloadAll} />}
          <RelatedComplaints key={c.complaint_id} complaintId={c.complaint_id} earlierCount={c.previous_related_count} />
          <Notes complaintId={c.complaint_id} notes={notes.data} onAdded={reloadAll} />
          <Timeline events={audit.data} />
        </aside>
      </div>
    </div>
  )
}
