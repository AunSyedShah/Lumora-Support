import { useRef, useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { PaperclipIcon } from '../../components/icons'
import { Button, Card, ErrorNotice, Loading, SuccessNotice } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const FINISHED = ['resolved', 'closed']

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
          {notes.length > 0 && (
            <ul className="m-0 mt-2 pl-5">
              {notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </SuccessNotice>
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

      <div className="flex flex-col gap-4">
        <Bubble mine name="You" at={c.created_at}>
          {c.description}
        </Bubble>
        {c.messages.map((m) => (
          <Bubble key={`${m.at}-${m.text.slice(0, 20)}`} mine={m.sender === 'customer'} name={m.name} at={m.at}>
            {m.text}
          </Bubble>
        ))}
        {c.messages.length === 0 && <p className="m-0 text-[15px] text-muted">The team will reply here. You’ll also hear from us by {c.preferred_contact}.</p>}
      </div>

      {c.attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 text-sm">
          {c.attachments.map((a) => (
            <span key={a.id} className="inline-flex items-center gap-1.5 rounded-full bg-sand px-3 py-1.5">
              <PaperclipIcon size={16} />
              {a.original_filename}
            </span>
          ))}
        </div>
      )}

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
