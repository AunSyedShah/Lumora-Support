import { useRef, useState } from 'react'

import { api, errorMessage } from '../../api/client'
import Attachments from '../../components/Attachments'
import { Button, Card, ErrorNotice, Loading, SuccessNotice } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { useApi } from '../../lib/useApi'

// What happens before our first reply, depending on how the customer wants to hear from us.
const AWAITING_REPLY = {
  email: 'The team will reply here, and we’ll email you a copy — you can answer straight from your inbox.',
  phone: 'The team will reply here, and may call you if that’s quicker.',
  chat: 'The team will reply here.',
}

const FINISHED = ['resolved', 'closed']

/** Notes from the intake checks, in words that help rather than worry. */
function friendlyNote(note) {
  if (/no order reference/i.test(note)) return 'If this is about an order, reply with the order number (e.g. ORD-10042) — it helps us check dates and return windows faster.'
  if (/no product was specified/i.test(note)) return null // not something the customer needs to act on
  const order = note.match(/different from the product on order (\S+?)\.?$/i)
  if (order) return `We’ve noted both the product you picked and order ${order[1]} — no need to change anything.`
  return note
}

function progressSteps(complaint) {
  const handled = !['new', 'analyzed'].includes(complaint.status)
  const replied = complaint.messages.some((m) => m.sender === 'lumora')
  const done = FINISHED.includes(complaint.status)
  return [
    { label: 'Received', done: true },
    { label: complaint.department ? `With ${complaint.department}` : 'With the right team', done: handled },
    { label: 'We replied', done: replied },
    { label: 'Resolved', done },
  ]
}

function Bubble({ mine, name, at, children }) {
  return (
    <div className={`flex max-w-[82%] flex-col gap-1.5 ${mine ? 'items-end self-end' : 'items-start self-start'}`}>
      <p className={`m-0 px-5 py-3.5 text-base leading-relaxed whitespace-pre-line ${mine ? 'rounded-[18px_4px_18px_18px] bg-sand' : 'rounded-[4px_18px_18px_18px] bg-mint'}`}>{children}</p>
      <span className="text-[13px] text-muted">
        {name} · {formatDateTime(at)}
      </span>
    </div>
  )
}

export default function ComplaintConversation({ complaintId, justSent, notes, onChange }) {
  const detail = useApi(`/complaints/my/${complaintId}`)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')
  const fileInput = useRef(null)

  if (detail.loading && !detail.data) return <Loading />
  if (detail.error) return <ErrorNotice message={detail.error} onRetry={detail.reload} />
  const c = detail.data
  const finished = FINISHED.includes(c.status)
  const intakeNotes = notes.map(friendlyNote).filter(Boolean)

  async function send() {
    if (!text.trim()) return
    setBusy(true)
    setError('')
    setDone('')
    try {
      await api.post(`/workflow/my/complaints/${complaintId}/${finished ? 'reopen' : 'reply'}`, { text: text.trim() })
      setText('')
      setDone(finished ? 'We’ve reopened your complaint and the team will look at it again.' : 'Sent. We’ll get back to you here.')
      detail.reload()
      onChange?.()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function attach(event) {
    const file = event.target.files?.[0]
    if (!file) return
    setBusy(true)
    setError('')
    const form = new FormData()
    form.append('file', file)
    try {
      await api.post(`/complaints/${complaintId}/attachments`, form)
      setDone(`${file.name} was added to your complaint.`)
      detail.reload()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
      event.target.value = ''
    }
  }

  return (
    <Card aria-label={c.title} className="flex min-w-0 flex-col gap-6 px-6 py-7 md:px-9">
      <div className="flex flex-col gap-1.5">
        <p className="m-0 text-sm text-muted">
          {[c.complaint_id, c.order_ref && `Order ${c.order_ref}`, c.product, `sent ${formatDateTime(c.created_at)}`].filter(Boolean).join(' · ')}
        </p>
        <h2 className="m-0 font-display text-[28px] font-bold tracking-tight">{c.title}</h2>
      </div>

      {justSent && (
        <SuccessNotice>
          <strong>Thanks — we’ve got it.</strong> Your reference is {c.complaint_id}.
          {intakeNotes.length > 0 && (
            <ul className="m-0 mt-2 pl-5">
              {intakeNotes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </SuccessNotice>
      )}

      {c.safety_concern && !FINISHED.includes(c.status) && (
        <div role="note" className="flex flex-col gap-1 rounded-2xl bg-sun-soft px-5 py-4 text-sun-ink">
          <strong>Please stay safe while we look into this</strong>
          <span>Stop using the device and switch it off at the plug or breaker if you can do so safely. If there is smoke, fire or a burning smell that gets worse, leave the area and call the emergency services.</span>
        </div>
      )}

      <ol aria-label="Progress" className="m-0 grid list-none grid-cols-4 gap-2 p-0 text-sm">
        {progressSteps(c).map((step) => (
          <li key={step.label} className="flex flex-col gap-2">
            <span className={`h-1.5 rounded-full ${step.done ? 'bg-forest' : 'bg-line-soft'}`} />
            <span className={step.done ? 'font-semibold' : 'text-muted'}>
              {step.label}
              <span className="sr-only">{step.done ? ' (done)' : ' (not yet)'}</span>
            </span>
          </li>
        ))}
      </ol>
      {c.reply_expected_by && (
        <p className="m-0 -mt-2 rounded-2xl bg-sand px-4 py-3 text-[15px]">
          {c.messages.some((m) => m.sender === 'lumora') ? 'We aim to have this sorted by ' : 'We’ll reply by '}
          <strong>{formatDateTime(c.reply_expected_by)}</strong>.
        </p>
      )}

      <div className="flex flex-col gap-4">
        <Bubble mine name="You" at={c.created_at}>
          {c.description}
        </Bubble>
        {c.messages.map((m) => (
          <Bubble key={`${m.at}-${m.text.slice(0, 20)}`} mine={m.sender === 'customer'} name={m.name} at={m.at}>
            {m.text}
          </Bubble>
        ))}
        {c.messages.length === 0 && <p className="m-0 text-[15px] text-muted">{AWAITING_REPLY[c.preferred_contact] || AWAITING_REPLY.email}</p>}
      </div>

      <Attachments complaintId={c.complaint_id} files={c.attachments} />

      <div className="flex flex-col gap-2">
        <label htmlFor="answer" className="text-[15px] font-semibold">
          {finished ? 'Still not fixed? Tell us and we’ll reopen it' : 'Write back'}
        </label>
        <textarea
          id="answer"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={finished ? 'What is still wrong?' : 'Add anything that might help us'}
          className="w-full resize-y rounded-[14px] border-[1.5px] border-line px-4 py-3 text-base focus:border-forest focus:outline-none"
        />
        <ErrorNotice message={error} />
        <SuccessNotice>{done}</SuccessNotice>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={send} disabled={busy || !text.trim()}>
            {finished ? 'Reopen complaint' : 'Send'}
          </Button>
          {!finished && (
            <>
              <Button variant="ghost" onClick={() => fileInput.current?.click()} disabled={busy}>
                Attach a photo
              </Button>
              <input ref={fileInput} type="file" accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={attach} className="hidden" aria-label="Attach a photo or document" />
            </>
          )}
        </div>
      </div>
    </Card>
  )
}
