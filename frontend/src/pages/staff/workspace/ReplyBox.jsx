import { useState } from 'react'

import { api, errorMessage } from '../../../api/client'
import { FULL_ACCESS_ROLES, useAuth } from '../../../auth/context'
import { Button, ErrorNotice, SuccessNotice } from '../../../components/ui'
import { formatDateTime } from '../../../lib/format'
import { replyProblem } from '../../../lib/labels'

/** "Dear customer," -> "Dear Sara," when we know the customer's name. */
function personalise(text, firstName) {
  return firstName ? (text || '').replace(/^(Dear|Hi|Hello) customer\b/i, `$1 ${firstName}`) : text
}

/**
 * The reply to the customer, pre-filled with the suggested reply. Every reply is checked by the
 * API before it goes out; a reviewer can still send it with a written reason.
 */
export default function ReplyBox({ complaint, blocked, onSent }) {
  const { user } = useAuth()
  const alreadySent = Boolean(complaint.response_sent_at)
  const fullName = complaint.customer_name || complaint.customer
  const firstName = complaint.customer_name && complaint.customer_name !== complaint.customer ? complaint.customer_name.split(' ')[0] : null
  const [text, setText] = useState(alreadySent ? '' : personalise(complaint.response_text, firstName))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [problem, setProblem] = useState(null)
  const [override, setOverride] = useState('')
  const [sent, setSent] = useState('')
  const canOverride = FULL_ACCESS_ROLES.includes(user.role)

  async function send(withOverride = false) {
    setBusy(true)
    setError('')
    setSent('')
    try {
      await api.post(`/workflow/complaints/${complaint.complaint_id}/send-response`, {
        text: text.trim(),
        override_reason: withOverride ? override.trim() : null,
      })
      setProblem(null)
      setOverride('')
      setText('')
      setSent('Reply sent. The customer can see it in their complaint.')
      onSent()
    } catch (e) {
      const message = errorMessage(e)
      const parsed = replyProblem(message)
      setProblem(parsed)
      setError(parsed ? '' : message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2.5">
      <label htmlFor="reply" className="font-display text-lg font-bold">
        {alreadySent ? 'Send another reply' : `Your reply to ${fullName}`}
      </label>
      {alreadySent && <p className="m-0 text-sm text-muted">Last reply sent {formatDateTime(complaint.response_sent_at)}.</p>}
      {complaint.resolution?.response_requires_rewrite && !alreadySent && (
        <p className="m-0 rounded-xl bg-sun-soft px-4 py-2.5 text-[15px] text-sun-ink">The suggested reply needs rewriting before it’s sent — check it against the policy notes.</p>
      )}
      <textarea
        id="reply"
        rows={6}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="w-full resize-y rounded-[14px] border-[1.5px] border-line bg-[#fffdf9] px-4 py-3.5 text-base leading-relaxed focus:border-forest focus:outline-none"
      />
      {problem && (
        <div role="alert" className="flex flex-col gap-2 rounded-2xl bg-sun-soft px-5 py-4 text-sun-ink">
          <span>{problem.text}</span>
          <ul className="m-0 pl-5">
            {problem.quotes.map((q) => (
              <li key={q}>“{q}”</li>
            ))}
          </ul>
          {canOverride && (
            <div className="mt-1 flex flex-wrap items-end gap-2">
              <label className="flex flex-1 flex-col gap-1 text-sm font-semibold">
                Or send it anyway — why is it OK?
                <input value={override} onChange={(e) => setOverride(e.target.value)} className="rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] font-normal text-ink" />
              </label>
              <Button variant="light" disabled={busy || override.trim().length < 5} onClick={() => send(true)}>
                Send anyway
              </Button>
            </div>
          )}
        </div>
      )}
      <ErrorNotice message={error} />
      <SuccessNotice>{sent}</SuccessNotice>
      <div className="flex flex-wrap items-center gap-2.5">
        <Button onClick={() => send(false)} disabled={busy || blocked || !text.trim()}>
          {busy ? 'Sending…' : 'Send reply'}
        </Button>
        {blocked && <span className="text-sm text-muted">You can reply once the second look is done.</span>}
      </div>
    </div>
  )
}
