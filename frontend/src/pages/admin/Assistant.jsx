import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, ErrorNotice, Loading, SectionTitle, SuccessNotice } from '../../components/ui'
import { formatDate } from '../../lib/format'
import { useApi } from '../../lib/useApi'
import { fieldLabel, input } from './style'

const NAME = { complaint_analysis: 'Reading complaints and suggesting a plan' }

/** "1.3" -> "1.4" (a suggestion for the next version number). */
function nextVersion(versions) {
  const [major, minor = 0] = versions
    .map((v) => v.split('.').map(Number))
    .sort((a, b) => b[0] - a[0] || (b[1] || 0) - (a[1] || 0))[0] || [1, 0]
  return `${major}.${minor + 1}`
}

function NewVersion({ from, versions, onSaved, onClose }) {
  const [form, setForm] = useState({ version: nextVersion(versions), description: '', system_prompt: from.system_prompt, user_prompt: from.user_prompt, activate: false })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.post('/genai/prompts', { ...form, name: from.name })
      onSaved(`Version ${form.version} was saved${form.activate ? ' and is now in use' : ''}.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="form" onSubmit={save} className="flex flex-col gap-4 p-6">
      <SectionTitle>New version, based on {from.version}</SectionTitle>
      <p className="m-0 text-[15px] text-muted">Earlier versions are never changed, so we can always see which instructions handled a complaint.</p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[140px_minmax(0,1fr)]">
        <label className={fieldLabel}>
          Version
          <input required value={form.version} onChange={set('version')} pattern="\d+(\.\d+){0,2}" className={input} />
        </label>
        <label className={fieldLabel}>
          What changed
          <input value={form.description} onChange={set('description')} placeholder="e.g. Clearer wording on refunds" className={input} />
        </label>
      </div>
      <label className={fieldLabel}>
        Standing instructions
        <textarea rows={10} value={form.system_prompt} onChange={set('system_prompt')} className={`${input} font-mono text-[13px]`} />
      </label>
      <label className={fieldLabel}>
        Message for each complaint (keep the ${'{…}'} blanks, they are filled in for every complaint)
        <textarea rows={14} value={form.user_prompt} onChange={set('user_prompt')} className={`${input} font-mono text-[13px]`} />
      </label>
      <label className="flex items-center gap-2 text-[15px]">
        <input type="checkbox" checked={form.activate} onChange={set('activate')} className="size-4 accent-forest" />
        Start using it straight away
      </label>
      <ErrorNotice message={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save version'}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </Card>
  )
}

function Viewer({ prompt, onActivate, onCopy }) {
  const detail = useApi(`/genai/prompts/${prompt.name}/${prompt.version}`)
  return (
    <Card className="flex min-w-0 flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionTitle>Version {prompt.version}</SectionTitle>
        <div className="flex gap-2">
          {!prompt.is_active && <Button onClick={() => onActivate(prompt)}>Start using this version</Button>}
          {detail.data && (
            <Button variant="light" onClick={() => onCopy(detail.data)}>
              Make a new version from this
            </Button>
          )}
        </div>
      </div>
      <ErrorNotice message={detail.error} onRetry={detail.reload} />
      {detail.loading && <Loading />}
      {detail.data && (
        <>
          <h3 className="m-0 text-[15px] font-semibold">Standing instructions</h3>
          <pre className="m-0 max-h-80 overflow-auto rounded-2xl bg-sand p-4 text-[13px] leading-relaxed whitespace-pre-wrap">{detail.data.system_prompt}</pre>
          <h3 className="m-0 text-[15px] font-semibold">Message for each complaint</h3>
          <pre className="m-0 max-h-96 overflow-auto rounded-2xl bg-sand p-4 text-[13px] leading-relaxed whitespace-pre-wrap">{detail.data.user_prompt}</pre>
        </>
      )}
    </Card>
  )
}

export default function Assistant() {
  const prompts = useApi('/genai/prompts')
  const [viewing, setViewing] = useState(null)
  const [copyFrom, setCopyFrom] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const list = [...(prompts.data || [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  const shown = viewing && list.find((p) => p.id === viewing)

  async function activate(prompt) {
    setError('')
    setMessage('')
    try {
      await api.post(`/genai/prompts/${prompt.name}/${prompt.version}/activate`)
      setMessage(`Version ${prompt.version} is now in use for new complaints.`)
      prompts.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
      <Card className="flex flex-col gap-4 p-6">
        <SectionTitle>Instruction versions</SectionTitle>
        <p className="m-0 text-[15px] text-muted">The assistant follows these instructions when it reads a new complaint. Our rules always check its suggestion afterwards.</p>
        <ErrorNotice message={error || prompts.error} onRetry={prompts.error ? prompts.reload : undefined} />
        <SuccessNotice>{message}</SuccessNotice>
        {prompts.loading && !prompts.data && <Loading />}
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {list.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => {
                  setViewing(p.id)
                  setCopyFrom(null)
                }}
                className={`flex w-full flex-col gap-1 rounded-2xl border-[1.5px] p-4 text-left ${viewing === p.id ? 'border-forest bg-mint' : 'border-line bg-white hover:bg-cream'}`}
              >
                <span className="flex flex-wrap items-center gap-2 font-semibold">
                  Version {p.version} {p.is_active && <Badge tone="green">In use</Badge>}
                </span>
                <span className="text-[14px] text-muted">
                  {NAME[p.name] || p.name} · added {formatDate(p.created_at)} · used for {p.analyses} complaint{p.analyses === 1 ? '' : 's'}
                </span>
                {p.description && <span className="text-[14px]">{p.description}</span>}
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {copyFrom ? (
        <NewVersion
          from={copyFrom}
          versions={list.filter((p) => p.name === copyFrom.name).map((p) => p.version)}
          onClose={() => setCopyFrom(null)}
          onSaved={(text) => {
            setCopyFrom(null)
            setMessage(text)
            prompts.reload()
          }}
        />
      ) : shown ? (
        <Viewer key={shown.id} prompt={shown} onActivate={activate} onCopy={setCopyFrom} />
      ) : (
        <Card className="p-6 text-muted">Pick a version to read its instructions.</Card>
      )}
    </div>
  )
}
