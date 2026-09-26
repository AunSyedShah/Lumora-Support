import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import WorkCard from '../../components/WorkCard'
import { Button, EmptyState, ErrorNotice, Loading, PageTitle } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { useApi } from '../../lib/useApi'

export default function FollowUps() {
  const [overdueOnly, setOverdueOnly] = useState(false)
  const list = useApi('/workflow/follow-ups', { params: { overdue_only: overdueOnly } })
  const [error, setError] = useState('')

  async function markDone(complaintId) {
    setError('')
    try {
      await api.post(`/workflow/complaints/${complaintId}/follow-up-done`, { comment: '' })
      list.reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageTitle eyebrow="Check back with customers after a complaint is handled" title="Follow-ups">
        <label className="flex items-center gap-2 text-[15px]">
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} className="size-4 accent-forest" />
          Only overdue
        </label>
      </PageTitle>
      <ErrorNotice message={error || list.error} onRetry={list.error ? list.reload : undefined} />
      {list.loading && !list.data && <Loading />}
      {list.data?.length === 0 && <EmptyState title="No follow-ups due">You’re all caught up.</EmptyState>}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {list.data?.map((item) => (
          <div key={item.complaint_id} className="flex flex-col gap-2">
            <WorkCard item={item} to={`/work/complaints/${item.complaint_id}`}>
              <span className="text-muted">Follow up by {formatDateTime(item.follow_up_due)}</span>
            </WorkCard>
            <Button variant="light" className="self-start" onClick={() => markDone(item.complaint_id)}>
              Mark follow-up done
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
