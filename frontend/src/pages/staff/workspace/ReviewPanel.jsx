import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../../../api/client'
import { Button, ErrorNotice, Loading, SectionTitle, Select } from '../../../components/ui'
import { COMPENSATION, ESCALATION, PRIORITY, reviewReasons } from '../../../lib/labels'
import { useTaxonomy } from '../../../lib/taxonomy'
import { useApi } from '../../../lib/useApi'

/**
 * A reviewer's second look: why it was flagged, the suggestion next to what our policies say,
 * and the decision. "Our policies say" is the checked result that will be used when approved.
 */
function comparisonRows(suggested, validation, names) {
  const final = validation.final_resolution || {}
  const rows = [
    ['Problem', names.subcategoryName(suggested.primary_issue?.subcategory), names.subcategoryName(final.subcategory)],
    ['Team', names.departmentName(suggested.department), names.departmentName(final.department)],
    ['Urgency', suggested.urgency, final.urgency],
    ['Priority', PRIORITY[suggested.priority], PRIORITY[final.priority]],
    ['Escalate to', ESCALATION[suggested.escalation_level], ESCALATION[final.escalation_level]],
    ['Offer', COMPENSATION[suggested.compensation?.type], COMPENSATION[final.compensation?.type]],
  ]
  return rows.map(([label, a, b]) => ({ label, suggested: a || '—', policies: b || '—', differs: Boolean(a && b && a !== b) }))
}

export default function ReviewPanel({ complaint, work, onDone }) {
  const names = useTaxonomy()
  const validation = useApi(`/validation/complaints/${complaint.complaint_id}/latest`)
  const analysis = useApi(`/genai/complaints/${complaint.complaint_id}/latest`, { params: { successful_only: true } })
  const [mode, setMode] = useState(null) // null | 'edit' | 'reclassify' | 'reject'
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [edit, setEdit] = useState({ priority: complaint.priority, escalation_level: complaint.escalation_level || 'none', response_text: complaint.response_text })
  const [subcategory, setSubcategory] = useState(complaint.subcategory || '')

  const id = complaint.complaint_id
  const navigate = useNavigate()

  /** After a decision, go straight to the next complaint that needs a second look. */
  async function goToNext() {
    const { data } = await api.get('/workflow/review-queue')
    const next = data.find((item) => item.complaint_id !== id)
    if (next) navigate(`/complaints/${next.complaint_id}`, { state: { reviewed: id, left: data.filter((i) => i.complaint_id !== id).length } })
    else navigate('/review', { state: { reviewed: id } })
  }

  // `decided`: the complaint leaves the review queue, so move on to the next one.
  async function run(steps, decided = false) {
    setBusy(true)
    setError('')
    try {
      for (const [url, body] of steps) await api.post(`/workflow/complaints/${id}/${url}`, body)
      setMode(null)
      setNote('')
      if (decided) await goToNext()
      else onDone()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const subcategoryOptions = (names.taxonomy?.categories || []).flatMap((c) => c.subcategories.map((s) => ({ value: s.code, label: `${c.name} — ${s.name}` })))
  const suggested = analysis.data?.output
  const rows = suggested && validation.data ? comparisonRows(suggested, validation.data, names) : []
  const rejected = work.review_status === 'rejected'
  // Our rules' own reading of the words, when it names another problem than the one that would be kept.
  const final = validation.data?.final_resolution || {}
  const otherReading = validation.data?.independent_expected?.subcategory
  const hint = otherReading && final.subcategory && otherReading !== final.subcategory ? otherReading : null

  return (
    <section aria-label="Second look" className="flex flex-col gap-5 rounded-[26px] border-2 border-sun bg-white p-7">
      <div className="flex flex-col gap-2">
        <SectionTitle>{rejected ? 'The suggestion was sent back — decide how to handle it' : 'Needs a second look'}</SectionTitle>
        <ul className="m-0 flex flex-col gap-1 pl-5 text-[15px]">
          {reviewReasons(work.review_reasons).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </div>

      {(validation.loading || analysis.loading) && !rows.length && <Loading label="Loading the comparison…" />}
      {rows.length > 0 && (
        <table className="w-full border-collapse text-[15px]">
          <caption className="pb-2 text-left font-semibold">
            Suggested plan vs. our policies
            {complaint.verification_score != null && (
              <span className="ml-2 font-normal text-muted">
                · score <strong className="text-ink">{complaint.verification_score}</strong>/100
                {rows.some((r) => r.differs) ? ', differences highlighted' : complaint.verification_score >= 90 ? ', they agree' : ' — same plan; the reasons above explain the lower score'}
              </span>
            )}
          </caption>
          <thead>
            <tr className="text-left text-[13px] text-muted">
              <th scope="col" className="border-b border-line-soft py-2 pr-3 font-semibold" />
              <th scope="col" className="border-b border-line-soft px-3 py-2 font-semibold">Suggested</th>
              <th scope="col" className="border-b border-line-soft px-3 py-2 font-semibold">Our policies say</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className={r.differs ? 'bg-sun-soft' : ''}>
                <th scope="row" className="border-b border-sand-2 py-2.5 pr-3 pl-2 text-left font-semibold">
                  {r.label}
                  {r.differs && <span className="sr-only"> (different)</span>}
                </th>
                <td className="border-b border-sand-2 px-3 py-2.5">{r.suggested}</td>
                <td className={`border-b border-sand-2 px-3 py-2.5 ${r.differs ? 'font-semibold' : ''}`}>{r.policies}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {hint && (
        <p className="m-0 rounded-2xl bg-sand px-4 py-3 text-[15px]">
          From the words alone, our rules would call this <strong>{names.subcategoryName(hint)}</strong>. If that fits better, use <em>Change problem type</em> before approving.
        </p>
      )}
      {!suggested && !analysis.loading && <p className="m-0 text-[15px] text-muted">There is no automatic suggestion for this complaint — decide from the complaint and our policies.</p>}

      <label className="flex flex-col gap-1.5 text-[15px] font-semibold">
        Note for the team <span className="font-normal text-muted">(optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. replacement approved, check stock first" className="rounded-[14px] border-[1.5px] border-line px-4 py-2.5 text-[15px] font-normal" />
      </label>

      {mode === 'edit' && (
        <div className="flex flex-col gap-3 rounded-2xl bg-sand p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Select label="Priority" value={edit.priority} onChange={(v) => setEdit({ ...edit, priority: v })} options={Object.entries(PRIORITY).map(([value, label]) => ({ value, label }))} />
            <Select label="Escalate to" value={edit.escalation_level} onChange={(v) => setEdit({ ...edit, escalation_level: v })} options={Object.entries(ESCALATION).map(([value, label]) => ({ value, label }))} />
          </div>
          <label className="flex flex-col gap-1 text-[13px] text-muted">
            Reply to the customer
            <textarea rows={5} value={edit.response_text} onChange={(e) => setEdit({ ...edit, response_text: e.target.value })} className="rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] text-ink" />
          </label>
          <Button className="self-start" disabled={busy} onClick={() => run([['modify', { ...edit, comment: note }], ['approve', { comment: note }]], true)}>
            Save changes and approve
          </Button>
        </div>
      )}
      {mode === 'reclassify' && (
        <div className="flex flex-col gap-3 rounded-2xl bg-sand p-4">
          <Select label="What is the problem really about?" value={subcategory} onChange={setSubcategory} options={subcategoryOptions} />
          <p className="m-0 text-sm text-muted">The team, priority and escalation are worked out again from our policies for the new problem type.</p>
          <Button className="self-start" disabled={busy || !subcategory} onClick={() => run([['reclassify', { subcategory, comment: note }]])}>
            Change problem type
          </Button>
        </div>
      )}
      {mode === 'reject' && (
        <div className="flex flex-col gap-3 rounded-2xl bg-sand p-4">
          <p className="m-0 text-[15px]">Add a note above saying what’s wrong with the suggestion, then send it back.</p>
          <Button variant="light" className="self-start" disabled={busy || note.trim().length < 3} onClick={() => run([['reject', { comment: note }]])}>
            Send the suggestion back
          </Button>
        </div>
      )}

      <ErrorNotice message={error} />
      <div className="flex flex-wrap items-center gap-2.5">
        <Button disabled={busy} onClick={() => run([['approve', { comment: note }]], true)}>
          Go with our policies
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => setMode(mode === 'edit' ? null : 'edit')} aria-expanded={mode === 'edit'}>
          Edit before approving
        </Button>
        <Button variant="light" disabled={busy} onClick={() => {
            if (hint && mode !== 'reclassify') setSubcategory(hint)
            setMode(mode === 'reclassify' ? null : 'reclassify')
          }} aria-expanded={mode === 'reclassify'}>
          Change problem type
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => run([['regenerate', { tone: null }]])}>
          {busy ? 'Working…' : 'Ask for a new suggestion'}
        </Button>
        {!rejected && (
          <Button variant="ghost" disabled={busy} onClick={() => setMode(mode === 'reject' ? null : 'reject')} aria-expanded={mode === 'reject'}>
            Send it back
          </Button>
        )}
      </div>
    </section>
  )
}
