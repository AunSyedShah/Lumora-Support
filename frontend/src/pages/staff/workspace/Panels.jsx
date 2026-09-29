import { useState } from 'react'

import { api, errorMessage } from '../../../api/client'
import { AlertIcon, CheckIcon } from '../../../components/icons'
import { Button, Card, ErrorNotice, SectionTitle } from '../../../components/ui'
import { formatDateTime } from '../../../lib/format'
import { AUDIT, COMPENSATION, ESCALATION, NEXT_STATUS, STAFF_STATUS, STATUS_ACTION } from '../../../lib/labels'
import { plainText, usePolicyNames } from '../../../lib/policies'
import { useApi } from '../../../lib/useApi'

/** "What we suggest": the checked plan (the rule matrix has already been applied to it). */
export function Suggestion({ resolution }) {
  const policyName = usePolicyNames()
  const steps = resolution?.resolution_steps || []
  if (!steps.length) return null
  return (
    <section className="flex flex-col gap-3 rounded-[22px] bg-forest p-6 text-cream">
      <SectionTitle>What we suggest</SectionTitle>
      <ol className="m-0 flex flex-col gap-2 pl-5 text-[15px] leading-snug">
        {steps.map((s) => (
          <li key={s}>{plainText(s, policyName)}</li>
        ))}
      </ol>
      {resolution.escalation_level && resolution.escalation_level !== 'none' && (
        <p className="m-0 mt-1 rounded-xl bg-forest-2 px-4 py-2.5 text-[15px]">
          Escalated to <strong>{ESCALATION[resolution.escalation_level]}</strong>
          {resolution.escalation_notes?.reason && ` — ${plainText(resolution.escalation_notes.reason, policyName)}`}
        </p>
      )}
    </section>
  )
}

function CheckLine({ ok, children }) {
  return (
    <li className="flex items-start gap-2.5 text-[15px] leading-snug">
      <span className={`mt-0.5 shrink-0 ${ok ? 'text-forest' : 'text-amber'}`}>{ok ? <CheckIcon size={20} /> : <AlertIcon size={20} />}</span>
      <span>{children}</span>
    </li>
  )
}

/** A list that stays folded until the agent wants it, so the page leads with what to do. */
function More({ title, items, policyName }) {
  if (!items.length) return null
  return (
    <details className="rounded-xl bg-sand px-4 py-2.5">
      <summary className="cursor-pointer text-[15px] font-semibold">
        {title} ({items.length})
      </summary>
      <ul className="m-0 mt-2 flex flex-col gap-1 pl-5 text-[15px] text-muted">
        {items.map((t) => (
          <li key={t}>{plainText(t, policyName)}</li>
        ))}
      </ul>
    </details>
  )
}

/** How well the suggestion matched our rules (the verification score, 0-100), in words. */
function scoreText(score) {
  if (score >= 90) return 'matches our policies closely'
  if (score >= 75) return 'mostly matches our policies'
  return 'differs from our policies in places'
}

/** "Checked against our policies": what's allowed, what to avoid, what to ask. */
export function PolicyCheck({ resolution, score }) {
  const policyName = usePolicyNames()
  const compensation = resolution?.compensation?.type
  // "none" only means nothing was offered yet: the rule tells us what may still be offered.
  const rule = useApi(resolution?.resolution_rule && (!compensation || compensation === 'none') ? `/rules/resolution/${resolution.resolution_rule}` : null)
  if (!resolution || Object.keys(resolution).length === 0) {
    // Not analysed yet: say so rather than show "nothing is due", which nobody has checked.
    return (
      <Card className="flex flex-col gap-2 p-6">
        <SectionTitle>Not checked yet</SectionTitle>
        <p className="m-0 text-[15px] text-muted">This complaint hasn’t been through the automatic check against our policies, so there is no suggested plan. Handle it from the complaint and our policies.</p>
      </Card>
    )
  }
  const refs = resolution.policy_references || []
  const avoid = resolution.prohibited_actions || []
  const tips = resolution.agent_guidance || []
  const questions = resolution.clarification_questions || []
  const stillAllowed = (rule.data?.allowed_compensation || []).filter((c) => c !== 'none')
  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle>Checked against our policies</SectionTitle>
        {score != null && (
          <span className="text-[15px] text-muted" title="Verification score: how closely the automatic suggestion matched our rules">
            Score <strong className="text-ink">{score}</strong>/100
          </span>
        )}
      </div>
      {score != null && <p className="m-0 text-sm text-muted">The suggestion {scoreText(score)}.</p>}
      <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
        {compensation && compensation !== 'none' ? (
          <CheckLine ok>
            {COMPENSATION[compensation]} is allowed{resolution.compensation.policy_id ? ` (${policyName(`${resolution.compensation.policy_id} ${resolution.compensation.section || ''}`.trim())})` : ''}
          </CheckLine>
        ) : stillAllowed.length ? (
          <CheckLine ok>Nothing offered yet. If the case qualifies, our policies allow: {stillAllowed.map((c) => (COMPENSATION[c] || c).toLowerCase()).join(' or ')}</CheckLine>
        ) : (
          <CheckLine ok>No refund or compensation is due for this case</CheckLine>
        )}
        {avoid.map((a) => (
          <CheckLine key={a}>Don’t: {a.charAt(0).toLowerCase() + a.slice(1)}</CheckLine>
        ))}
      </ul>
      {refs.length > 0 && <p className="m-0 text-sm text-muted">Based on {refs.map(policyName).join('; ')}</p>}
      <More title="Tips" items={tips} policyName={policyName} />
      <More title="Questions you may need to ask" items={questions} policyName={policyName} />
    </Card>
  )
}

const ESCALATE_TO = ['supervisor', 'department_manager', 'specialist_team', 'compliance_review', 'critical_management']

/** Status changes, escalation and the follow-up, in plain words. */
export function Actions({ complaint, work, canEscalate, inReview, onDone }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [escalating, setEscalating] = useState(false)
  const [level, setLevel] = useState('supervisor')
  const [reason, setReason] = useState('')
  // While a reviewer takes a second look, the complaint cannot be finished yet.
  const next = (NEXT_STATUS[complaint.status] || []).filter((s) => !inReview || !['resolved', 'closed'].includes(s))

  async function run(url, body) {
    setBusy(true)
    setError('')
    try {
      await api.post(`/workflow/complaints/${complaint.complaint_id}/${url}`, body)
      setEscalating(false)
      setReason('')
      onDone()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle>Status</SectionTitle>
        <span className="text-[15px] text-muted">
          {STAFF_STATUS[complaint.status]}
          {work.assigned_to && ` · with ${work.assigned_to_name || work.assigned_to}`}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {next.map((status) => (
          <Button key={status} variant={status === 'resolved' ? 'primary' : 'light'} disabled={busy} onClick={() => run('status', { status, comment: '' })}>
            {STATUS_ACTION[status]}
          </Button>
        ))}
        {canEscalate && !['resolved', 'closed'].includes(complaint.status) && (
          <Button variant="ghost" disabled={busy} onClick={() => setEscalating((v) => !v)} aria-expanded={escalating}>
            Escalate
          </Button>
        )}
      </div>
      {escalating && (
        <div className="flex flex-col gap-3 rounded-2xl bg-sand p-4">
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Escalate to
            <select value={level} onChange={(e) => setLevel(e.target.value)} className="rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] font-normal">
              {ESCALATE_TO.map((l) => (
                <option key={l} value={l}>
                  {ESCALATION[l]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Why?
            <input value={reason} onChange={(e) => setReason(e.target.value)} className="rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] font-normal" />
          </label>
          <Button className="self-start" disabled={busy || reason.trim().length < 3} onClick={() => run('escalate', { level, comment: reason.trim() })}>
            Escalate now
          </Button>
        </div>
      )}
      {inReview && <p className="m-0 text-sm text-muted">It can be resolved once the second look is done.</p>}
      {complaint.follow_up_due && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line-soft pt-3 text-[15px]">
          <span>Follow up with the customer by {formatDateTime(complaint.follow_up_due)}</span>
          <Button variant="light" disabled={busy} onClick={() => run('follow-up-done', { comment: '' })}>
            Follow-up done
          </Button>
        </div>
      )}
      <ErrorNotice message={error} />
    </Card>
  )
}

/** Internal notes (optionally shown to the customer). */
export function Notes({ complaintId, notes, onAdded }) {
  const [text, setText] = useState('')
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState('')
  const internal = (notes || []).filter((n) => !n.customer_visible)

  async function add() {
    setBusy(true)
    setError('')
    setSent('')
    try {
      await api.post(`/workflow/complaints/${complaintId}/notes`, { text: text.trim(), customer_visible: visible })
      setSent(visible ? 'Sent to the customer — it is in the conversation now.' : '')
      setText('')
      setVisible(false)
      onAdded()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="flex flex-col gap-3 p-6">
      <SectionTitle>Team notes</SectionTitle>
      {internal.length === 0 && <p className="m-0 text-[15px] text-muted">No notes yet.</p>}
      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {internal.map((n) => (
          <li key={n.id} className="flex flex-col gap-0.5 text-[15px]">
            <span>{n.text}</span>
            <span className="text-[13px] text-muted">
              {n.author_name || n.author || 'System'} · {formatDateTime(n.created_at)}
            </span>
          </li>
        ))}
      </ul>
      <label htmlFor="note" className="sr-only">
        Add a note
      </label>
      <textarea id="note" rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a note for the team" className="w-full resize-y rounded-[14px] border-[1.5px] border-line px-4 py-2.5 text-[15px] focus:border-forest focus:outline-none" />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)} className="size-4 accent-forest" />
          Also show it to the customer
        </label>
        <Button variant="light" disabled={busy || !text.trim()} onClick={add}>
          {visible ? 'Send to customer' : 'Add note'}
        </Button>
      </div>
      <ErrorNotice message={error} />
      {sent && <p className="m-0 text-sm font-semibold text-forest">{sent}</p>}
    </Card>
  )
}

/** What happened so far (the audit trail), newest last. */
export function Timeline({ events }) {
  if (!events?.length) return null
  return (
    <Card className="flex flex-col gap-3 p-6">
      <SectionTitle>Timeline</SectionTitle>
      <ol className="m-0 flex list-none flex-col gap-2.5 p-0 text-[14px]">
        {events.map((e) => {
          const status = e.after?.status && e.before?.status !== e.after.status ? ` → ${STAFF_STATUS[e.after.status] || e.after.status}` : ''
          return (
            <li key={e.id} className="flex flex-col">
              <span>
                <strong className="font-semibold">{AUDIT[e.action] || e.action}</strong>
                {status}
              </span>
              <span className="text-[13px] text-muted">
                {formatDateTime(e.created_at)}
                {(e.actor_name || e.actor) && ` · ${e.actor_name || e.actor}`}
              </span>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
