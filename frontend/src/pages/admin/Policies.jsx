import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, EmptyState, ErrorNotice, Loading, SectionTitle, Select, SuccessNotice } from '../../components/ui'
import { formatDate, isPast } from '../../lib/format'
import { humanize } from '../../lib/labels'
import { useApi } from '../../lib/useApi'
import DocumentViewer from './DocumentViewer'
import { input } from './style'

const STATUS = { active: 'In use', previous: 'Previous version', superseded: 'Replaced', draft: 'Draft' }
const STATUS_TONE = { active: 'green', draft: 'sun', previous: 'sand', superseded: 'sand' }
const TYPES = ['policy', 'sop', 'faq', 'sla', 'routing', 'compliance', 'template', 'other']
const TYPE_NAME = { sop: 'Procedure (SOP)', faq: 'FAQ', sla: 'Service levels', policy: 'Policy', routing: 'Routing', compliance: 'Compliance', template: 'Reply templates', other: 'Other' }

function UploadForm({ onUploaded }) {
  const [file, setFile] = useState(null)
  const [meta, setMeta] = useState({ doc_id: '', title: '', version: '', doc_type: '', status: 'active', effective_date: '', expiry_date: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')
  const set = (key) => (e) => setMeta({ ...meta, [key]: e.target.value })

  async function upload(e) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setError('')
    setDone('')
    const form = new FormData()
    form.append('file', file)
    Object.entries(meta).forEach(([k, v]) => v && form.append(k, v))
    try {
      const { data } = await api.post('/kb/documents', form)
      setDone(`${data.document.title} (version ${data.document.version}) was added.${data.warnings.length ? ' Note: ' + data.warnings.join(' ') : ''}`)
      setFile(null)
      e.target.reset()
      onUploaded()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="form" onSubmit={upload} className="flex flex-col gap-4 p-6">
      <SectionTitle>Add a policy document</SectionTitle>
      <p className="m-0 text-[15px] text-muted">PDF or Word (.docx). The ID, version and dates are read from the document; fill them in only to override. An expired document is never used for new resolutions.</p>
      <input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] || null)} aria-label="Document file" className="text-[15px]" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          Document ID
          <input value={meta.doc_id} onChange={set('doc_id')} placeholder="e.g. REF-POL" className={input} />
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          Version
          <input value={meta.version} onChange={set('version')} placeholder="e.g. 2.0" className={input} />
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          Takes effect on
          <input type="date" value={meta.effective_date} onChange={set('effective_date')} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          Stops applying on (optional)
          <input type="date" value={meta.expiry_date} min={meta.effective_date || undefined} onChange={set('expiry_date')} className={input} />
        </label>
        <label className="col-span-2 flex flex-col gap-1 text-[13px] text-muted md:col-span-1">
          Title
          <input value={meta.title} onChange={set('title')} className={input} />
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          Kind
          <select value={meta.doc_type} onChange={set('doc_type')} className={input}>
            <option value="">From the document</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_NAME[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-muted">
          Use it
          <select value={meta.status} onChange={set('status')} className={input}>
            <option value="active">Now (replaces the current version)</option>
            <option value="draft">Later (save as draft)</option>
          </select>
        </label>
      </div>
      <ErrorNotice message={error} />
      <SuccessNotice>{done}</SuccessNotice>
      <Button type="submit" className="self-start" disabled={!file || busy}>
        {busy ? 'Reading the document…' : 'Upload'}
      </Button>
    </Card>
  )
}

function Search() {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const hits = useApi(query ? '/kb/search' : null, { params: { q: query, limit: 5 } })
  return (
    <Card className="flex flex-col gap-4 p-6">
      <SectionTitle>Find in our policies</SectionTitle>
      <form
        role="search"
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          setQuery(q.trim())
        }}
      >
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. refund after 30 days" aria-label="Search policies" className={`${input} min-w-0 flex-1`} />
        <Button type="submit" variant="light">
          Search
        </Button>
      </form>
      {hits.loading && <Loading />}
      {hits.data?.length === 0 && <p className="m-0 text-muted">Nothing found.</p>}
      <ol className="m-0 flex list-none flex-col gap-3 p-0">
        {hits.data?.map((h) => (
          <li key={h.chunk_id} className="rounded-2xl bg-sand p-4">
            <p className="m-0 text-sm font-semibold">
              {h.title} · section {h.section || '—'} {h.heading}
            </p>
            <p className="m-0 mt-1 text-[15px] leading-relaxed">{h.text}</p>
          </li>
        ))}
      </ol>
    </Card>
  )
}

export default function Policies() {
  const docs = useApi('/kb/documents')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [reading, setReading] = useState(null)

  async function update(doc, change) {
    if (change === 'delete' && !window.confirm(`Delete the draft “${doc.title}” (version ${doc.version})? This cannot be undone.`)) return
    setError('')
    try {
      if (change === 'delete') await api.delete(`/kb/documents/${doc.id}`)
      else await api.patch(`/kb/documents/${doc.id}`, { status: change })
      docs.reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const list = (docs.data || []).filter((d) => !status || d.status === status).sort((a, b) => a.doc_id.localeCompare(b.doc_id) || b.version.localeCompare(a.version))

  return (
    <div className="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <Card className="flex min-w-0 flex-col gap-4 p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <SectionTitle>Policy documents</SectionTitle>
          <Select label="Show" value={status} onChange={setStatus} options={[{ value: '', label: 'All versions' }, ...Object.entries(STATUS).map(([value, label]) => ({ value, label }))]} />
        </div>
        <ErrorNotice message={error || docs.error} onRetry={docs.error ? docs.reload : undefined} />
        {docs.loading && !docs.data && <Loading />}
        {docs.data && list.length === 0 && <EmptyState title="No documents" />}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-[15px]">
            <thead>
              <tr className="text-left text-[13px] text-muted">
                {['Document', 'Kind', 'Version', 'Status', 'In effect', ''].map((h) => (
                  <th key={h} scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((d) => (
                <tr key={d.id}>
                  <td className="border-b border-sand-2 px-2 py-2.5">
                    <button type="button" onClick={() => setReading(d)} className="cursor-pointer border-0 bg-transparent p-0 text-left font-semibold text-forest underline-offset-4 hover:underline">
                      {d.title.replace(/^Lumora Home Technologies\s*[-–]\s*/, '')}
                    </button>
                    <div className="text-[13px] text-muted">
                      {d.doc_id} · {d.chunk_count} sections
                    </div>
                  </td>
                  <td className="border-b border-sand-2 px-2 py-2.5">{TYPE_NAME[d.doc_type] || humanize(d.doc_type)}</td>
                  <td className="border-b border-sand-2 px-2 py-2.5">{d.version}</td>
                  <td className="border-b border-sand-2 px-2 py-2.5">
                    <Badge tone={STATUS_TONE[d.status]}>{STATUS[d.status] || d.status}</Badge>
                  </td>
                  <td className="border-b border-sand-2 px-2 py-2.5 whitespace-nowrap">
                    {d.expiry_date ? `${formatDate(d.effective_date)} – ${formatDate(d.expiry_date)}` : `from ${formatDate(d.effective_date)}`}
                    {d.expiry_date && isPast(`${d.expiry_date}T23:59:59`) && (
                      <Badge tone="warn" className="ml-2">
                        Expired
                      </Badge>
                    )}
                  </td>
                  <td className="border-b border-sand-2 px-2 py-2.5 text-right whitespace-nowrap">
                    {d.status === 'draft' && (
                      <span className="flex justify-end gap-1">
                        <Button variant="light" onClick={() => update(d, 'active')}>
                          Start using
                        </Button>
                        <Button variant="ghost" onClick={() => update(d, 'delete')}>
                          Delete
                        </Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="flex flex-col gap-5">
        {reading ? (
          <DocumentViewer key={reading.id} doc={reading} onPick={setReading} onClose={() => setReading(null)} />
        ) : (
          <>
            <UploadForm onUploaded={docs.reload} />
            <Search />
          </>
        )}
      </div>
    </div>
  )
}
