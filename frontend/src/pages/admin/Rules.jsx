import { useState } from 'react'

import { api, downloadFile, errorMessage } from '../../api/client'
import { Badge, Button, Card, ErrorNotice, Loading, SectionTitle, Select, SuccessNotice } from '../../components/ui'
import { COMPENSATION, ESCALATION, PRIORITY } from '../../lib/labels'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'
import { input } from './style'


/** A rule's conditions as a sentence ("late by 6+ working days, amount 500+ USD"). */
function describe(conditions, names) {
  const parts = []
  for (const [key, value] of Object.entries(conditions || {})) {
    const list = Array.isArray(value) ? value : [value]
    if (key === 'keywords_any') parts.push(`mentions “${list.slice(0, 3).join('”, “')}”${list.length > 3 ? '…' : ''}`)
    else if (key === 'categories') parts.push(`problem type is ${list.map(names.categoryName).join(' or ')}`)
    else if (key === 'subcategories') parts.push(`problem is ${list.map(names.subcategoryName).join(' or ')}`)
    else if (key === 'customer_types') parts.push(`${list.join(' or ')} customer`)
    else if (key === 'products') parts.push(`product is ${list.join(' or ')}`)
    else if (key === 'min_amount') parts.push(`amount ${value}+ USD`)
    else if (key === 'max_amount') parts.push(`amount up to ${value} USD`)
    else if (key === 'min_days_late') parts.push(`late by ${value}+ working days`)
    else if (key === 'min_days_since_delivery') parts.push(`${value}+ days after delivery`)
    else if (key === 'max_days_since_delivery') parts.push(`within ${value} days of delivery`)
    else if (key === 'min_days_since_purchase') parts.push(`${value}+ days after purchase`)
    else if (key === 'max_days_since_purchase') parts.push(`within ${value} days of purchase`)
    else if (key === 'min_previous_complaints') parts.push(`${value}+ earlier complaints`)
    else parts.push(`${key} ${value}`)
  }
  return parts.join(', ') || 'always'
}

function Tester() {
  const [text, setText] = useState('')
  const [amount, setAmount] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const names = useTaxonomy()

  async function run(e) {
    e.preventDefault()
    setError('')
    try {
      const { data } = await api.post('/rules/evaluate', { text, amount: amount ? Number(amount) : null, previous_complaints: 0 })
      setResult(data)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <Card as="form" onSubmit={run} className="flex flex-col gap-3 p-6">
      <SectionTitle>Try the rules</SectionTitle>
      <p className="m-0 text-[15px] text-muted">Type a complaint to see how our rules would sort it — no complaint is created.</p>
      <label htmlFor="try-text" className="sr-only">
        Complaint text
      </label>
      <textarea id="try-text" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. My smart plug smells like burning plastic" className={input} />
      <label className="flex flex-col gap-1 text-[13px] text-muted">
        Order amount in USD (optional)
        <input type="number" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} className={`${input} w-40`} />
      </label>
      <Button type="submit" variant="light" className="self-start" disabled={text.trim().length < 5}>
        Check
      </Button>
      <ErrorNotice message={error} />
      {result && (
        <dl className="m-0 grid grid-cols-[140px_minmax(0,1fr)] gap-x-3 gap-y-1.5 rounded-2xl bg-sand p-4 text-[15px]">
          <dt className="text-muted">Problem</dt>
          <dd className="m-0">{result.subcategory ? names.subcategoryName(result.subcategory) : 'Couldn’t tell — a person would decide'}</dd>
          <dt className="text-muted">Team</dt>
          <dd className="m-0">{names.departmentName(result.department) || '—'}</dd>
          <dt className="text-muted">Priority</dt>
          <dd className="m-0">{PRIORITY[result.priority] || '—'}</dd>
          <dt className="text-muted">Escalate to</dt>
          <dd className="m-0">{ESCALATION[result.escalation_level]}</dd>
          <dt className="text-muted">May offer</dt>
          <dd className="m-0">{result.allowed_compensation.map((c) => COMPENSATION[c]).join(', ') || '—'}</dd>
        </dl>
      )}
    </Card>
  )
}

function ImportExport({ type, onImported }) {
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function upload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setMessage('')
    setError('')
    const form = new FormData()
    form.append('file', file)
    try {
      const { data } = await api.post(`/rules/import/${type}`, form)
      setMessage(`${data.created} added and ${data.updated} updated (${data.total} rules in the file).`)
      onImported()
    } catch (err) {
      const errors = err.response?.data?.errors
      setError(errors?.length ? `${errorMessage(err)} ${errors.slice(0, 3).join(' ')}` : errorMessage(err))
    } finally {
      e.target.value = ''
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="light" onClick={() => downloadFile(`/rules/export/${type}`, { format: 'csv' }, `${type}_rules.csv`).catch((err) => setError(errorMessage(err)))}>
          Download as CSV
        </Button>
        <label className="inline-flex min-h-11 cursor-pointer items-center rounded-full border-[1.5px] border-line bg-white px-5 text-[15px] font-semibold text-forest hover:bg-mint">
          Upload a CSV
          <input type="file" accept=".csv" onChange={upload} className="sr-only" />
        </label>
      </div>
      <ErrorNotice message={error} />
      <SuccessNotice>{message}</SuccessNotice>
    </div>
  )
}

export default function Rules() {
  const names = useTaxonomy()
  const [kind, setKind] = useState('resolution')
  const [category, setCategory] = useState('')
  const rules = useApi(kind === 'resolution' ? '/rules/resolution' : '/rules/escalation', { params: kind === 'resolution' && category ? { category } : {} })
  const [error, setError] = useState('')

  async function toggle(rule) {
    setError('')
    try {
      await api.patch(`/rules/${kind}/${rule.rule_id}`, { is_active: !rule.is_active })
      rules.reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <Card className="flex min-w-0 flex-col gap-4 p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <SectionTitle>{kind === 'resolution' ? 'How each problem is handled' : 'When to escalate'}</SectionTitle>
          <div className="flex flex-wrap gap-2">
            <Select
              label="Rules"
              value={kind}
              onChange={setKind}
              options={[
                { value: 'resolution', label: 'Handling rules' },
                { value: 'escalation', label: 'Escalation rules' },
              ]}
            />
            {kind === 'resolution' && (
              <Select label="Problem type" value={category} onChange={setCategory} options={[{ value: '', label: 'All types' }, ...(names.taxonomy?.categories || []).map((c) => ({ value: c.code, label: c.name }))]} />
            )}
          </div>
        </div>
        <ErrorNotice message={error || rules.error} onRetry={rules.error ? rules.reload : undefined} />
        {rules.loading && !rules.data && <Loading />}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-[14px]">
            <thead>
              <tr className="text-left text-[13px] text-muted">
                {(kind === 'resolution' ? ['Problem', 'When', 'Team', 'Priority', 'Escalate to', 'On'] : ['Rule', 'When', 'Escalate to', 'Team', 'On']).map((h) => (
                  <th key={h} scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(rules.data || []).map((r) => (
                <tr key={r.rule_id} className={r.is_active ? '' : 'text-muted'}>
                  <td className="border-b border-sand-2 px-2 py-2">
                    <div className="font-semibold">{kind === 'resolution' ? names.subcategoryName(r.subcategory) : r.name}</div>
                    <div className="text-[12px] text-muted">{r.rule_id}</div>
                  </td>
                  <td className="border-b border-sand-2 px-2 py-2">{describe(r.conditions, names)}</td>
                  {kind === 'resolution' ? (
                    <>
                      <td className="border-b border-sand-2 px-2 py-2">{names.departmentName(r.department)}</td>
                      <td className="border-b border-sand-2 px-2 py-2">{PRIORITY[r.priority]}</td>
                      <td className="border-b border-sand-2 px-2 py-2">{ESCALATION[r.escalation_level]}</td>
                    </>
                  ) : (
                    <>
                      <td className="border-b border-sand-2 px-2 py-2">{ESCALATION[r.escalation_level]}</td>
                      <td className="border-b border-sand-2 px-2 py-2">{names.departmentName(r.target_department) || '—'}</td>
                    </>
                  )}
                  <td className="border-b border-sand-2 px-2 py-2">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={r.is_active} onChange={() => toggle(r)} className="size-4 accent-forest" aria-label={`Rule ${r.rule_id} in use`} />
                      {!r.is_active && <Badge tone="sand">Off</Badge>}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="flex flex-col gap-5">
        <Tester />
        <Card className="flex flex-col gap-3 p-6">
          <SectionTitle>Edit many rules at once</SectionTitle>
          <p className="m-0 text-[15px] text-muted">Download the {kind === 'resolution' ? 'handling' : 'escalation'} rules, change them in Excel, and upload the file again.</p>
          <ImportExport type={kind} onImported={rules.reload} />
        </Card>
      </div>
    </div>
  )
}
