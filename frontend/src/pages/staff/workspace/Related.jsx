import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, errorMessage } from '../../../api/client'
import { useAuth } from '../../../auth/context'
import { Badge, Button, Card, ErrorNotice, SectionTitle } from '../../../components/ui'
import { timeAgo } from '../../../lib/format'
import { ROLE, STAFF_STATUS } from '../../../lib/labels'
import { useTaxonomy } from '../../../lib/taxonomy'
import { useApi } from '../../../lib/useApi'

/** Similarity score in words (the same limits the backend uses for duplicates and repeats). */
function likeness(score) {
  if (score >= 0.97) return 'Almost the same'
  if (score >= 0.85) return 'Very similar'
  return 'Similar'
}

function ComplaintLink({ id, title, children }) {
  return (
    <li className="flex flex-col gap-0.5 border-b border-sand-2 py-2.5 last:border-0">
      <Link to={`/complaints/${id}`} className="font-semibold text-forest">
        {title}
      </Link>
      <span className="text-[14px] text-muted">
        {id} · {children}
      </span>
    </li>
  )
}

/** What to say when none of the customer's earlier complaints can be listed here. */
function noEarlierText(role, earlierCount) {
  if (role !== 'agent') return 'This is their first complaint.'
  if (earlierCount > 0) return `They complained about this ${earlierCount === 1 ? 'once' : `${earlierCount} times`} before; that went to another team.`
  return 'None that reached your team.'
}

/** The customer's earlier complaints, and complaints that read alike (duplicates / repeats). */
export function RelatedComplaints({ complaintId, earlierCount = 0 }) {
  const history = useApi(`/complaints/${complaintId}/history`)
  const similar = useApi(`/complaints/${complaintId}/similar`, { params: { k: 5 } })
  const { categoryName } = useTaxonomy()
  const { user } = useAuth()
  const earlier = history.data || []
  const alike = (similar.data || []).filter((s) => s.similarity >= 0.6)

  return (
    <Card className="flex flex-col gap-4 p-6">
      <SectionTitle>Related complaints</SectionTitle>
      <ErrorNotice message={history.error || similar.error} />
      <div className="flex flex-col gap-1">
        <h3 className="m-0 text-[15px] font-semibold">Earlier from this customer</h3>
        {history.data && earlier.length === 0 && (
          <p className="m-0 text-[15px] text-muted">{noEarlierText(user.role, earlierCount)}</p>
        )}
        <ul className="m-0 list-none p-0">
          {earlier.slice(0, 5).map((c) => (
            <ComplaintLink key={c.complaint_id} id={c.complaint_id} title={c.title}>
              {[categoryName(c.category), STAFF_STATUS[c.status], timeAgo(c.created_at)].filter(Boolean).join(' · ')}
            </ComplaintLink>
          ))}
        </ul>
        {earlier.length > 5 && <p className="m-0 text-[14px] text-muted">and {earlier.length - 5} more</p>}
      </div>
      <div className="flex flex-col gap-1">
        <h3 className="m-0 text-[15px] font-semibold">Complaints that read alike</h3>
        {similar.data && alike.length === 0 && <p className="m-0 text-[15px] text-muted">Nothing close.</p>}
        <ul className="m-0 list-none p-0">
          {alike.map((s) => (
            <ComplaintLink key={s.complaint_id} id={s.complaint_id} title={s.title}>
              {likeness(s.similarity)} · {STAFF_STATUS[s.status]} {s.same_customer && <Badge tone="soft">Same customer</Badge>}
            </ComplaintLink>
          ))}
        </ul>
      </div>
    </Card>
  )
}

/** Move the complaint to another team and/or person (reviewers, managers, admins). */
export function HandOver({ complaint, work, onDone }) {
  const { user } = useAuth()
  const { taxonomy } = useTaxonomy()
  const canListPeople = ['manager', 'admin'].includes(user.role)
  const staff = useApi(canListPeople ? '/auth/users' : null)
  const [open, setOpen] = useState(false)
  const [department, setDepartment] = useState('')
  const [assignee, setAssignee] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const people = (staff.data || []).filter((u) => u.role !== 'customer')
  const field = 'rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] font-normal'

  async function save() {
    setBusy(true)
    setError('')
    try {
      await api.post(`/workflow/complaints/${complaint.complaint_id}/assign`, { department: department || null, assignee: assignee.trim() || null, comment: comment.trim() })
      setOpen(false)
      setDepartment('')
      setAssignee('')
      setComment('')
      onDone()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="flex flex-col gap-3 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle>Who handles it</SectionTitle>
        <Button variant="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? 'Cancel' : 'Hand over'}
        </Button>
      </div>
      <p className="m-0 text-[15px] text-muted">
        {taxonomy?.names.department[complaint.department_code] || 'No team yet'} · {work.assigned_to ? `with ${work.assigned_to}` : 'nobody assigned yet'}
      </p>
      {open && (
        <div className="flex flex-col gap-3 rounded-2xl bg-sand p-4">
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Team
            <select value={department} onChange={(e) => setDepartment(e.target.value)} className={field}>
              <option value="">Keep the same team</option>
              {(taxonomy?.departments || []).map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Person
            {canListPeople ? (
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)} className={field}>
                <option value="">{department ? 'Whoever is free in that team' : 'Keep the same person'}</option>
                {people.map((u) => (
                  <option key={u.username} value={u.username}>
                    {`${u.first_name} ${u.last_name}`.trim() || u.username} ({ROLE[u.role].toLowerCase()})
                  </option>
                ))}
              </select>
            ) : (
              <input value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="Their username (optional)" className={field} />
            )}
          </label>
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Why? <span className="font-normal text-muted">(shown in the history)</span>
            <input value={comment} onChange={(e) => setComment(e.target.value)} className={field} />
          </label>
          <ErrorNotice message={error} />
          <Button className="self-start" disabled={busy || (!department && !assignee.trim())} onClick={save}>
            {busy ? 'Saving…' : 'Hand over'}
          </Button>
        </div>
      )}
    </Card>
  )
}
