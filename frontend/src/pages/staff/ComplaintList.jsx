import { useState } from 'react'
import { Link } from 'react-router-dom'

import Filters from '../../components/Filters'
import { Badge, Button, EmptyState, ErrorNotice, Loading, PageTitle, Select } from '../../components/ui'
import { EMPTY_FILTERS, filterParams } from '../../lib/filters'
import { timeAgo } from '../../lib/format'
import { PRIORITY, PRIORITY_TONE, STAFF_STATUS } from '../../lib/labels'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'

const PAGE_SIZE = 25

const SHOW = [
  { value: '', label: 'Everything' },
  { value: 'escalated', label: 'Escalated' },
  { value: 'review', label: 'Waiting for a second look' },
  { value: 'flagged', label: 'Tried to instruct our system' },
  { value: 'repeat', label: 'Repeat complaints' },
]

function showParams(show) {
  if (show === 'escalated') return { escalated: true }
  if (show === 'review') return { verification: 'manual_review' }
  if (show === 'flagged') return { flagged_only: true }
  if (show === 'repeat') return { match_type: 'repeat' }
  return {}
}

export default function ComplaintList() {
  const names = useTaxonomy()
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS, days: '' })
  const [status, setStatus] = useState('')
  const [show, setShow] = useState('')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)

  const list = useApi('/complaints', {
    params: { ...filterParams(filters), ...showParams(show), status: status || undefined, q: query || undefined, page, page_size: PAGE_SIZE },
  })
  const items = list.data?.items || []
  const pages = Math.max(1, Math.ceil((list.data?.count || 0) / PAGE_SIZE))
  const change = (setter) => (value) => {
    setter(value)
    setPage(1)
  }
  const visible = items

  return (
    <div className="flex flex-col gap-5">
      <PageTitle eyebrow={list.data ? `${list.data.count} complaint${list.data.count === 1 ? '' : 's'}` : ' '} title="All complaints" />
      <form
        role="search"
        className="flex flex-wrap items-end gap-2.5"
        onSubmit={(e) => {
          e.preventDefault()
          setQuery(search.trim())
          setPage(1)
        }}
      >
        <label className="flex min-w-[260px] flex-1 flex-col gap-1 text-[13px] text-muted">
          Search
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Words, complaint number or customer"
            className="rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] text-ink focus:border-forest focus:outline-none"
          />
        </label>
        <Button type="submit" variant="light">
          Search
        </Button>
        <Select label="Status" value={status} onChange={change(setStatus)} options={[{ value: '', label: 'Any status' }, ...Object.entries(STAFF_STATUS).map(([value, label]) => ({ value, label }))]} />
        <Select label="Show" value={show} onChange={change(setShow)} options={SHOW} />
      </form>
      <Filters value={filters} onChange={change(setFilters)} />
      <ErrorNotice message={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data && visible.length === 0 && <EmptyState title="No complaints match">Try fewer filters or other words.</EmptyState>}
      {visible.length > 0 && (
        <div className="overflow-x-auto rounded-[22px] bg-white">
          <table className="w-full min-w-[860px] border-collapse text-[15px]">
            <thead>
              <tr className="text-left text-[13px] text-muted">
                {['Complaint', 'Customer', 'Problem type', 'Team', 'Priority', 'Status', 'Received'].map((h) => (
                  <th key={h} scope="col" className="border-b border-line-soft px-4 py-3 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => (
                <tr key={c.complaint_id} className="hover:bg-cream">
                  <td className="border-b border-sand-2 px-4 py-3">
                    <Link to={`/complaints/${c.complaint_id}`} className="font-semibold text-forest">
                      {c.title}
                    </Link>
                    <div className="text-[13px] text-muted">
                      {c.complaint_id}
                      {c.review_status === 'pending' && ' · waiting for a second look'}
                      {c.match_type === 'repeat' && ' · repeat'}
                    </div>
                  </td>
                  <td className="border-b border-sand-2 px-4 py-3">{c.customer}</td>
                  <td className="border-b border-sand-2 px-4 py-3">{c.category ? names.categoryName(c.category) : <span className="text-muted">Not sorted yet</span>}</td>
                  <td className="border-b border-sand-2 px-4 py-3">{names.departmentName(c.department)}</td>
                  <td className="border-b border-sand-2 px-4 py-3">{c.priority && <Badge tone={PRIORITY_TONE[c.priority]}>{PRIORITY[c.priority]}</Badge>}</td>
                  <td className="border-b border-sand-2 px-4 py-3">{STAFF_STATUS[c.status]}</td>
                  <td className="border-b border-sand-2 px-4 py-3 whitespace-nowrap text-muted">{timeAgo(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <nav aria-label="Pages" className="flex items-center gap-3">
          <Button variant="light" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span className="text-[15px] text-muted">
            Page {page} of {pages}
          </span>
          <Button variant="light" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </nav>
      )}
    </div>
  )
}
