import { useState } from 'react'

import WorkCard from '../../components/WorkCard'
import { EmptyState, ErrorNotice, Loading, PageTitle, Select } from '../../components/ui'
import { timeAgo } from '../../lib/format'
import { PRIORITY, reviewReasons } from '../../lib/labels'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'

export default function SecondLook() {
  const { taxonomy } = useTaxonomy()
  const [department, setDepartment] = useState('')
  const [priority, setPriority] = useState('')
  const [includeRejected, setIncludeRejected] = useState(true)
  const queue = useApi('/workflow/review-queue', {
    params: { department: department || undefined, priority: priority || undefined, include_rejected: includeRejected },
  })
  const items = queue.data || []
  const oldest = items.reduce((min, i) => (!min || i.created_at < min ? i.created_at : min), null)

  return (
    <div className="flex flex-col gap-6">
      <PageTitle eyebrow={items.length ? `${items.length} complaint${items.length === 1 ? '' : 's'} · oldest waiting since ${timeAgo(oldest)}` : 'Complaints a person should check before anything goes out'} title="Needs a second look" />
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Team" value={department} onChange={setDepartment} options={[{ value: '', label: 'All teams' }, ...(taxonomy?.departments || []).map((d) => ({ value: d.code, label: d.name }))]} />
        <Select label="Priority" value={priority} onChange={setPriority} options={[{ value: '', label: 'Any' }, ...Object.entries(PRIORITY).map(([value, label]) => ({ value, label }))]} />
        <label className="flex min-h-11 items-center gap-2 text-[15px]">
          <input type="checkbox" checked={includeRejected} onChange={(e) => setIncludeRejected(e.target.checked)} className="size-4 accent-forest" />
          Include suggestions sent back
        </label>
      </div>
      <ErrorNotice message={queue.error} onRetry={queue.reload} />
      {queue.loading && !queue.data && <Loading />}
      {queue.data && items.length === 0 && <EmptyState title="Nothing to check">Every suggestion has been checked. Nice work.</EmptyState>}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <WorkCard key={item.complaint_id} item={item} to={`/complaints/${item.complaint_id}`}>
            <span className="text-muted">Why: {reviewReasons(item.review_reasons)[0] || 'a person should check it'}</span>
          </WorkCard>
        ))}
      </div>
    </div>
  )
}
