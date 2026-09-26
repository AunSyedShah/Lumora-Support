import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, ErrorNotice, Loading, SectionTitle, Select, SuccessNotice } from '../../components/ui'
import { PRIORITY } from '../../lib/labels'
import { refreshTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'
import { codeFrom, fieldLabel, input } from './style'

const EMPTY_PROBLEM = { code: '', name: '', description: '', department: '', keywords: [], is_fallback: false, takes_precedence_over: [], is_active: true }

/** Edit one problem (or add a new one when `problem.code` is empty). */
function ProblemEditor({ problem, category, problems, teams, onSaved, onClose }) {
  const [form, setForm] = useState({ ...problem, department: problem.department || '', keywords: problem.keywords.join('\n') })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const isNew = !problem.code
  const set = (key, value) => setForm({ ...form, [key]: value })

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = {
      name: form.name.trim(),
      description: form.description.trim(),
      department: form.department || null,
      keywords: form.keywords.split(/[\n,]/),
      is_fallback: form.is_fallback,
      takes_precedence_over: form.takes_precedence_over,
      is_active: form.is_active,
    }
    try {
      if (isNew) await api.post('/catalog/subcategories', { ...body, code: codeFrom(form.name), category: category.code })
      else await api.patch(`/catalog/subcategories/${problem.code}`, body)
      refreshTaxonomy()
      onSaved(`“${body.name}” was saved.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const others = problems.filter((p) => p.code !== problem.code)
  const togglePrecedence = (code) =>
    set('takes_precedence_over', form.takes_precedence_over.includes(code) ? form.takes_precedence_over.filter((c) => c !== code) : [...form.takes_precedence_over, code])

  return (
    <form onSubmit={save} className="flex flex-col gap-4 rounded-2xl bg-sand p-5">
      <p className="m-0 font-display text-lg font-bold">{isNew ? `New problem in ${category.name}` : `Edit “${problem.name}”`}</p>
      <label className={fieldLabel}>
        Name
        <input required minLength={2} value={form.name} onChange={(e) => set('name', e.target.value)} className={input} />
      </label>
      <label className={fieldLabel}>
        What it means (helps the assistant tell similar problems apart)
        <textarea rows={2} value={form.description} onChange={(e) => set('description', e.target.value)} className={input} />
      </label>
      <label className={fieldLabel}>
        Team that handles it
        <select value={form.department} onChange={(e) => set('department', e.target.value)} className={input}>
          <option value="">Same as {category.name} ({teams.find((t) => t.code === category.default_department)?.name})</option>
          {teams.map((t) => (
            <option key={t.code} value={t.code}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <label className={fieldLabel}>
        Words and phrases that point to this problem — one per line
        <textarea rows={5} value={form.keywords} onChange={(e) => set('keywords', e.target.value)} className={input} />
      </label>
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-1 text-[13px] text-muted">When a complaint also fits one of these, pick this problem first</legend>
        <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
          {others.map((p) => (
            <label key={p.code} className={`flex cursor-pointer items-center gap-1.5 rounded-full border-[1.5px] px-3 py-1 text-[14px] ${form.takes_precedence_over.includes(p.code) ? 'border-forest bg-mint text-forest' : 'border-line bg-white'}`}>
              <input type="checkbox" checked={form.takes_precedence_over.includes(p.code)} onChange={() => togglePrecedence(p.code)} className="sr-only" />
              {p.name}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-[15px]">
        <input type="checkbox" checked={form.is_fallback} onChange={(e) => set('is_fallback', e.target.checked)} className="size-4 accent-forest" />
        Use only when no other problem fits
      </label>
      <label className="flex items-center gap-2 text-[15px]">
        <input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active', e.target.checked)} className="size-4 accent-forest" />
        In use
      </label>
      <ErrorNotice message={error} />
      <div className="flex gap-2">
        <Button type="submit" disabled={busy || form.name.trim().length < 2}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function ProblemTypes({ teams }) {
  const categories = useApi('/catalog/categories')
  const [picked, setPicked] = useState('')
  const categoryCode = picked || categories.data?.[0]?.code || ''
  const problems = useApi(categoryCode ? '/catalog/subcategories' : null, { params: { category: categoryCode } })
  const allProblems = useApi('/catalog/subcategories')
  const [editing, setEditing] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const category = categories.data?.find((c) => c.code === categoryCode)

  async function updateCategory(change) {
    setError('')
    try {
      await api.patch(`/catalog/categories/${categoryCode}`, change)
      refreshTaxonomy()
      categories.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  function saved(text) {
    setEditing(null)
    setMessage(text)
    problems.reload()
    allProblems.reload()
  }

  return (
    <Card className="flex min-w-0 flex-col gap-4 p-6">
      <SectionTitle>Problem types</SectionTitle>
      <ErrorNotice message={error || categories.error || problems.error} />
      {categories.loading && !categories.data && <Loading />}
      {category && (
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Problem type"
            value={categoryCode}
            onChange={(code) => {
              setPicked(code)
              setEditing(null)
              setMessage('')
            }}
            options={categories.data.map((c) => ({ value: c.code, label: c.is_active ? c.name : `${c.name} (not in use)` }))}
          />
          <Select label="Usually handled by" value={category.default_department} onChange={(code) => updateCategory({ default_department: code })} options={teams.map((t) => ({ value: t.code, label: t.name }))} />
          <label className="flex min-h-11 items-center gap-2 text-[15px]">
            <input type="checkbox" checked={category.is_active} onChange={() => updateCategory({ is_active: !category.is_active })} className="size-4 accent-forest" />
            In use
          </label>
        </div>
      )}
      <SuccessNotice>{message}</SuccessNotice>
      {editing && (
        <ProblemEditor key={editing.code || 'new'} problem={editing} category={category} problems={allProblems.data || []} teams={teams} onSaved={saved} onClose={() => setEditing(null)} />
      )}
      <ul className="m-0 flex list-none flex-col p-0">
        {(problems.data || []).map((p) => (
          <li key={p.code} className="flex flex-wrap items-center gap-3 border-b border-sand-2 py-3">
            <div className="min-w-0 flex-1">
              <p className={`m-0 font-semibold ${p.is_active ? '' : 'text-muted'}`}>
                {p.name} {!p.is_active && <Badge>Not in use</Badge>} {p.is_fallback && <Badge tone="soft">Last resort</Badge>}
              </p>
              <p className="m-0 text-[14px] text-muted">
                {teams.find((t) => t.code === p.routed_department)?.name} · {p.keywords.length} key phrase{p.keywords.length === 1 ? '' : 's'}
              </p>
            </div>
            <Button variant="light" onClick={() => setEditing(p)}>
              Edit
            </Button>
          </li>
        ))}
      </ul>
      {category && !editing && (
        <Button variant="outline" className="self-start" onClick={() => setEditing(EMPTY_PROBLEM)}>
          Add a problem
        </Button>
      )}
    </Card>
  )
}

function Teams({ teams, onChange }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')

  async function run(request) {
    setError('')
    try {
      await request()
      refreshTaxonomy()
      onChange()
      return true
    } catch (err) {
      setError(errorMessage(err))
      return false
    }
  }

  async function add(e) {
    e.preventDefault()
    if (await run(() => api.post('/catalog/departments', { code: codeFrom(name), name: name.trim(), description: description.trim() }))) {
      setName('')
      setDescription('')
    }
  }

  return (
    <Card className="flex flex-col gap-4 p-6">
      <SectionTitle>Teams</SectionTitle>
      <ErrorNotice message={error} />
      <ul className="m-0 flex list-none flex-col p-0">
        {teams.map((t) => (
          <li key={t.code} className="flex items-center gap-3 border-b border-sand-2 py-2.5">
            <div className="min-w-0 flex-1">
              <p className={`m-0 font-semibold ${t.is_active ? '' : 'text-muted'}`}>{t.name}</p>
              {t.description && <p className="m-0 text-[14px] text-muted">{t.description}</p>}
            </div>
            <label className="flex items-center gap-2 text-[14px] text-muted">
              <input type="checkbox" checked={t.is_active} onChange={() => run(() => api.patch(`/catalog/departments/${t.code}`, { is_active: !t.is_active }))} className="size-4 accent-forest" />
              In use
            </label>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="flex flex-col gap-2">
        <label className={fieldLabel}>
          New team
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Solar Products" className={input} />
        </label>
        <label className={fieldLabel}>
          What they look after
          <input value={description} onChange={(e) => setDescription(e.target.value)} className={input} />
        </label>
        <Button type="submit" variant="light" className="self-start" disabled={codeFrom(name).length < 2}>
          Add team
        </Button>
      </form>
    </Card>
  )
}

function ResponseTimeRow({ rule, onSaved }) {
  const [form, setForm] = useState({ response_hours: rule.response_hours, resolution_hours: rule.resolution_hours, at_risk_percent: rule.at_risk_percent })
  const [error, setError] = useState('')
  const changed = Object.keys(form).some((k) => Number(form[k]) !== rule[k])
  const number = (key) => ({ type: 'number', min: 1, value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }), className: `${input} w-20` })

  async function save() {
    setError('')
    try {
      await api.patch(`/catalog/sla-rules/${rule.priority}`, Object.fromEntries(Object.entries(form).map(([k, v]) => [k, Number(v)])))
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <tr>
      <th scope="row" className="border-b border-sand-2 px-2 py-2 text-left font-semibold">
        {PRIORITY[rule.priority]}
      </th>
      <td className="border-b border-sand-2 px-2 py-2">
        <input {...number('response_hours')} aria-label={`${PRIORITY[rule.priority]}: first reply within hours`} />
      </td>
      <td className="border-b border-sand-2 px-2 py-2">
        <input {...number('resolution_hours')} aria-label={`${PRIORITY[rule.priority]}: solved within hours`} />
      </td>
      <td className="border-b border-sand-2 px-2 py-2">
        <input {...number('at_risk_percent')} max={100} aria-label={`${PRIORITY[rule.priority]}: warn at percent`} />
      </td>
      <td className="border-b border-sand-2 px-2 py-2">
        {changed && (
          <Button variant="light" onClick={save}>
            Save
          </Button>
        )}
        {error && <span className="text-sm text-rust">{error}</span>}
      </td>
    </tr>
  )
}

function ResponseTimes() {
  const rules = useApi('/catalog/sla-rules')
  const order = ['P0', 'P1', 'P2', 'P3']
  return (
    <Card className="flex flex-col gap-3 p-6">
      <SectionTitle>Response times</SectionTitle>
      <p className="m-0 text-[15px] text-muted">In working hours. We warn the team once a complaint has used the given share of its time.</p>
      <ErrorNotice message={rules.error} onRetry={rules.reload} />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[15px]">
          <thead>
            <tr className="text-left text-[13px] text-muted">
              {['Priority', 'First reply (h)', 'Solved (h)', 'Warn at %', ''].map((h) => (
                <th key={h} scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...(rules.data || [])]
              .sort((a, b) => order.indexOf(a.priority) - order.indexOf(b.priority))
              .map((r) => (
                <ResponseTimeRow key={`${r.priority}-${r.response_hours}-${r.resolution_hours}-${r.at_risk_percent}`} rule={r} onSaved={rules.reload} />
              ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function Catalog() {
  const teams = useApi('/catalog/departments')
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      {teams.data ? <ProblemTypes teams={teams.data} /> : <Loading />}
      <div className="flex flex-col gap-5">
        <ErrorNotice message={teams.error} onRetry={teams.reload} />
        {teams.data && <Teams teams={teams.data} onChange={teams.reload} />}
        <ResponseTimes />
      </div>
    </div>
  )
}
