import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Card, ErrorNotice, Loading, SectionTitle, SuccessNotice } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const STATUS = {
  answered: ['Answered', 'green'],
  unanswered: ['Not in the documents', 'soft'],
  blocked: ['Refused', 'outline'],
  failed: ['Assistant unavailable', 'warn'],
}
const FILTERS = [
  ['', 'All'],
  ['unanswered', 'Not in the documents'],
  ['failed', 'Unavailable'],
  ['blocked', 'Refused'],
]
const TYPE = { policy: 'Policy', faq: 'FAQ', sla: 'Service levels', compliance: 'Compliance', sop: 'Internal procedure', routing: 'Routing rules', template: 'Response templates', other: 'Other' }

function Switch({ checked, onChange, disabled, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-8 w-14 shrink-0 cursor-pointer rounded-full border-0 transition-colors disabled:opacity-60 ${checked ? 'bg-forest' : 'bg-line'}`}
    >
      <span className={`absolute top-1 left-1 size-6 rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : ''}`} />
    </button>
  )
}

function Documents({ settings, onSave, busy }) {
  const docs = settings.documents
  const shared = docs.filter((d) => d.shared).map((d) => d.doc_id)
  const toggle = (id) => onSave({ shared_docs: shared.includes(id) ? shared.filter((x) => x !== id) : [...shared, id] })
  return (
    <Card className="flex flex-col gap-3 p-6">
      <SectionTitle>What customers can ask about</SectionTitle>
      <p className="m-0 text-[15px] text-muted">The assistant answers only from the documents ticked here. Internal guides are off by default; tick one only if customers may see what it says.</p>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {docs.map((d) => (
          <li key={d.doc_id}>
            <label className="flex cursor-pointer items-center gap-3 rounded-2xl bg-sand px-4 py-2.5 text-[15px]">
              <input type="checkbox" checked={d.shared} disabled={busy} onChange={() => toggle(d.doc_id)} className="size-4 accent-forest" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold">{d.title.replace('Lumora Home Technologies - ', '')}</span>
                <span className="text-[13px] text-muted">{TYPE[d.doc_type] || d.doc_type}</span>
              </span>
            </label>
          </li>
        ))}
        {docs.length === 0 && <li className="text-muted">No approved documents yet. Upload some under Policies.</li>}
      </ul>
    </Card>
  )
}

function Log() {
  const [status, setStatus] = useState('')
  const rows = useApi('/chatbot/exchanges', { params: status ? { status } : {} })
  return (
    <Card className="flex flex-col gap-3 p-6 xl:col-span-2">
      <SectionTitle>What customers asked</SectionTitle>
      <p className="m-0 text-[15px] text-muted">Questions the documents don’t answer show where a policy is missing or unclear. Nobody’s name is stored with a question.</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Show">
        {FILTERS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={status === value}
            onClick={() => setStatus(value)}
            className={`cursor-pointer rounded-full px-4 py-1.5 text-[14px] ${status === value ? 'border border-forest bg-forest font-semibold text-white' : 'border border-line bg-white text-ink hover:bg-sand'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <ErrorNotice message={rows.error} onRetry={rows.reload} />
      {rows.loading && !rows.data && <Loading />}
      {rows.data?.length === 0 && <p className="m-0 text-muted">Nothing here yet.</p>}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {(rows.data || []).map((r) => {
          const [label, tone] = STATUS[r.status] || [r.status, 'sand']
          return (
            <li key={r.id} className="flex flex-col gap-1 rounded-2xl bg-sand px-4 py-3 text-[15px]">
              <span className="flex flex-wrap items-center gap-2">
                <Badge tone={tone}>{label}</Badge>
                <span className="text-[13px] text-muted">{formatDateTime(r.created_at)}</span>
              </span>
              <strong>{r.question}</strong>
              {r.status === 'answered' && <span className="text-muted">{r.answer}</span>}
              {r.sources.length > 0 && <span className="text-[13px] text-muted">From: {r.sources.map((s) => s.title).join(' · ')}</span>}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

const OUTCOME = {
  replied: ['Answered', 'green'],
  lodged: ['Complaint opened', 'dark'],
  forwarded: ['Added to a complaint', 'sand'],
  ignored: ['Not answered', 'outline'],
  failed: ['Not answered (error)', 'warn'],
  pending: ['Being handled', 'soft'],
}
const REASON = {
  unknown_sender: 'Sender is not a registered customer',
  ambiguous_sender: 'Two customers share this address',
  automatic_mail: 'Automatic or no-reply mail',
  too_many_emails: 'Too many emails from this sender',
  refused: 'Tried to give the assistant orders',
  empty: 'Nothing but quoted text',
  ai_unavailable: 'The AI was unavailable',
  reply_not_sent: 'The reply could not be sent',
}

function EmailAssistantCard({ email, busy, error, message, onToggle }) {
  const checked = email.last_poll_at ? formatDateTime(email.last_poll_at) : 'not yet'
  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <SectionTitle>Email assistant</SectionTitle>
          <span className="text-[15px] font-semibold">{email.enabled ? 'On — answering customers’ emails' : 'Off — emails are left alone'}</span>
        </div>
        <Switch checked={email.enabled} disabled={busy} label="Email assistant" onChange={onToggle} />
      </div>
      <p className="m-0 text-[15px] text-muted">
        The same assistant, by email. Customers write from their registered address to ask a question, ask where their complaint stands (and whether it was escalated), or report a problem, and it opens the complaint for them. Mail from anyone else, and from robots, is never answered.
      </p>
      {!email.ready && <ErrorNotice message={`The mailbox is not set up yet. ${email.setup_hint}`} />}
      <ErrorNotice message={email.ready ? error : ''} />
      <SuccessNotice>{message}</SuccessNotice>
      {email.enabled && email.last_error && <ErrorNotice message={`The last check of the mailbox failed: ${email.last_error}`} />}
      {email.ready && (
        <p className="m-0 text-[14px] text-muted">
          Mailbox: {email.transport === 'gmail' ? 'Gmail (Agno)' : 'IMAP'} · last checked {checked} · {email.listening ? 'listening in this server' : 'not listening in this server (run “manage.py run_email_agent”)'}
        </p>
      )}
      <dl className="m-0 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ['Emails seen', email.stats.total],
          ['Answered', email.stats.replied],
          ['Complaints opened', email.stats.lodged],
          ['Added to complaints', email.stats.forwarded],
        ].map(([label, value]) => (
          <div key={label} className="flex flex-col rounded-2xl bg-sand px-4 py-3">
            <dd className="m-0 font-display text-[26px] font-bold">{value}</dd>
            <dt className="text-[13px] text-muted">{label}</dt>
          </div>
        ))}
      </dl>
    </Card>
  )
}

function EmailLog() {
  const [outcome, setOutcome] = useState('')
  const rows = useApi('/chatbot/email-exchanges', { params: outcome ? { outcome } : {} })
  return (
    <Card className="flex flex-col gap-3 p-6 xl:col-span-2">
      <SectionTitle>Customer emails</SectionTitle>
      <p className="m-0 text-[15px] text-muted">What each email was and what the assistant did. Customers are shown by name, never by address.</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Show emails">
        {[['', 'All'], ['lodged', 'Complaints opened'], ['replied', 'Answered'], ['ignored', 'Not answered'], ['failed', 'Errors']].map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={outcome === value}
            onClick={() => setOutcome(value)}
            className={`cursor-pointer rounded-full px-4 py-1.5 text-[14px] ${outcome === value ? 'border border-forest bg-forest font-semibold text-white' : 'border border-line bg-white text-ink hover:bg-sand'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <ErrorNotice message={rows.error} onRetry={rows.reload} />
      {rows.loading && !rows.data && <Loading />}
      {rows.data?.length === 0 && <p className="m-0 text-muted">No emails yet.</p>}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {(rows.data || []).map((m) => {
          const [label, tone] = OUTCOME[m.outcome] || [m.outcome, 'sand']
          return (
            <li key={m.id} className="flex flex-col gap-1 rounded-2xl bg-sand px-4 py-3 text-[15px]">
              <span className="flex flex-wrap items-center gap-2">
                <Badge tone={tone}>{label}</Badge>
                <span className="text-[13px] text-muted">
                  {m.customer_name || 'Unknown sender'} · {formatDateTime(m.received_at)}
                </span>
                {m.complaints.map((id) => (
                  <Badge key={id} tone="outline">
                    {id}
                  </Badge>
                ))}
              </span>
              <strong>{m.subject || '(no subject)'}</strong>
              {m.reason && <span className="text-[13px] text-muted">{REASON[m.reason] || m.reason}</span>}
              {m.body && <span className="line-clamp-2 text-muted">{m.body}</span>}
              {m.reply && (
                <details className="text-[14px]">
                  <summary className="cursor-pointer font-semibold text-forest">Reply that was sent</summary>
                  <p className="m-0 mt-1 whitespace-pre-line text-muted">{m.reply}</p>
                </details>
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

export default function ChatAssistant() {
  const settings = useApi('/chatbot/settings')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState({ scope: 'chat', error: '', message: '' }) // shown in the card the change was made in
  const s = settings.data
  const noticeFor = (scope) => (notice.scope === scope ? notice : { error: '', message: '' })

  async function save(changes, done, scope = 'chat') {
    setBusy(true)
    setNotice({ scope, error: '', message: '' })
    try {
      await api.put('/chatbot/settings', changes)
      setNotice({ scope, error: '', message: done || '' })
      settings.reload()
    } catch (e) {
      setNotice({ scope, error: errorMessage(e), message: '' })
    } finally {
      setBusy(false)
    }
  }

  if (settings.loading && !s) return <Loading />
  if (!s) return <ErrorNotice message={settings.error} onRetry={settings.reload} />

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <Card className="flex flex-col gap-4 p-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-col gap-1">
            <SectionTitle>Customer chat assistant</SectionTitle>
            <span className="text-[15px] font-semibold">{s.enabled ? 'On — customers see the chat button' : 'Off — customers don’t see it'}</span>
          </div>
          <Switch checked={s.enabled} disabled={busy} label="Customer chat assistant" onChange={(enabled) => save({ enabled }, enabled ? 'The chat assistant is now on.' : 'The chat assistant is now off.')} />
        </div>
        <p className="m-0 text-[15px] text-muted">
          Customers can ask general questions and get answers taken from the documents on the right. It can’t see anyone’s orders, accounts or complaints, and it never promises refunds or exceptions — when it doesn’t know, it points to sending a complaint.
        </p>
        <ErrorNotice message={noticeFor('chat').error} />
        <SuccessNotice>{noticeFor('chat').message}</SuccessNotice>
        {s.stats.last_error && <ErrorNotice message={`The last question could not be answered. ${s.stats.last_error}`} />}
        <dl className="m-0 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ['Questions', s.stats.total],
            ['Answered', s.stats.answered],
            ['Not in documents', s.stats.unanswered],
            ['Refused or failed', s.stats.blocked + s.stats.failed],
          ].map(([label, value]) => (
            <div key={label} className="flex flex-col rounded-2xl bg-sand px-4 py-3">
              <dd className="m-0 font-display text-[26px] font-bold">{value}</dd>
              <dt className="text-[13px] text-muted">{label}</dt>
            </div>
          ))}
        </dl>
      </Card>
      <EmailAssistantCard
        email={s.email}
        busy={busy}
        error={noticeFor('email').error}
        message={noticeFor('email').message}
        onToggle={(email_enabled) => save({ email_enabled }, email_enabled ? 'The email assistant is now on.' : 'The email assistant is now off.', 'email')}
      />
      <Documents settings={s} busy={busy} onSave={(changes) => save(changes, 'Saved. It applies to the next question.')} />
      <Log key={s.stats.total} />
      <EmailLog key={`email-${s.email.stats.total}`} />
    </div>
  )
}
