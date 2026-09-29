import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Button, Card, ErrorNotice, SectionTitle, Select } from '../../components/ui'
import { COMPENSATION, ESCALATION, PRIORITY } from '../../lib/labels'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'
import { fieldLabel, input } from './style'

/*
 * Add or change one rule of the Complaint Resolution Rule Matrix without leaving the app.
 * The conditions use the same small language as the CSV files (rules/conditions.py); the API
 * validates them, so a typo can never switch a rule off silently.
 */

const URGENCY = ['Low', 'Medium', 'High', 'Critical']
const CUSTOMER_TYPES = [
  { value: 'standard', label: 'Standard' },
  { value: 'premium', label: 'Premium' },
  { value: 'business', label: 'Business' },
]

// Condition key -> how it is asked. `list` values are alternatives (any of them matches).
const CONDITIONS = {
  keywords_any: { label: 'Mentions any of', kind: 'words', hint: 'comma-separated, e.g. burning, smoke' },
  categories: { label: 'Problem type is', kind: 'category' },
  subcategories: { label: 'Problem is', kind: 'subcategory' },
  customer_types: { label: 'Customer is', kind: 'customer' },
  products: { label: 'Product is', kind: 'product' },
  min_amount: { label: 'Amount at least (USD)', kind: 'number' },
  max_amount: { label: 'Amount at most (USD)', kind: 'number' },
  min_days_late: { label: 'Late by at least (working days)', kind: 'number' },
  min_days_since_delivery: { label: 'Days since delivery at least', kind: 'number' },
  max_days_since_delivery: { label: 'Days since delivery at most', kind: 'number' },
  min_days_since_purchase: { label: 'Days since purchase at least', kind: 'number' },
  max_days_since_purchase: { label: 'Days since purchase at most', kind: 'number' },
  min_previous_complaints: { label: 'Earlier complaints at least', kind: 'number' },
}

const lines = (text) => text.split('\n').map((l) => l.trim()).filter(Boolean)

/** {min_amount: 500, keywords_any: ["a","b"]} <-> [{key, value}] rows the form can edit. */
function toRows(conditions) {
  return Object.entries(conditions || {}).map(([key, value]) => ({ key, value: Array.isArray(value) ? value.join(', ') : String(value) }))
}

function fromRows(rows) {
  const conditions = {}
  for (const { key, value } of rows) {
    if (!key || String(value).trim() === '') continue
    const kind = CONDITIONS[key]?.kind
    conditions[key] = kind === 'number' ? Number(value) : String(value).split(',').map((v) => v.trim()).filter(Boolean)
  }
  return conditions
}

/** The next free number after the highest existing one: RR-113 -> RR-114. */
function nextId(rules, prefix) {
  const numbers = (rules || []).map((r) => Number(r.rule_id.replace(/\D/g, ''))).filter(Number.isFinite)
  return `${prefix}-${String(Math.max(0, ...numbers) + 1).padStart(3, '0')}`
}

function Choice({ value, onChange, label, items, className = '' }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={`${input} ${className}`} aria-label={label}>
      <option value="">Choose…</option>
      {items.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

function ConditionRow({ row, onChange, onRemove, names, products }) {
  const spec = CONDITIONS[row.key]
  const set = (value) => onChange({ ...row, value })
  const categories = names.taxonomy?.categories || []
  const choices = {
    category: categories.map((c) => ({ value: c.code, label: c.name })),
    subcategory: categories.flatMap((c) => c.subcategories.map((s) => ({ value: s.code, label: `${c.name} — ${s.name}` }))),
    customer: CUSTOMER_TYPES,
    product: products.map((p) => ({ value: p, label: p })),
  }
  // A condition with several alternatives ("premium, business") stays a comma-separated text field.
  const several = String(row.value).includes(',')
  let field
  if (spec.kind === 'number') field = <input type="number" min="0" value={row.value} onChange={(e) => set(e.target.value)} className={`${input} w-32`} aria-label={spec.label} />
  else if (choices[spec.kind] && !several) field = <Choice value={row.value} onChange={set} label={spec.label} items={choices[spec.kind]} className="min-w-0 flex-1" />
  else field = <input value={row.value} onChange={(e) => set(e.target.value)} placeholder={spec.hint} className={`${input} min-w-0 flex-1`} aria-label={spec.label} />
  return (
    <li className="flex flex-wrap items-center gap-2">
      <span className="w-full text-[13px] font-semibold text-muted sm:w-52">{spec.label}</span>
      {field}
      <Button variant="ghost" onClick={onRemove} aria-label={`Remove “${spec.label}”`}>
        Remove
      </Button>
    </li>
  )
}

function ConditionsBuilder({ rows, setRows, required }) {
  const names = useTaxonomy()
  const productList = useApi('/catalog/products')
  const products = (productList.data || []).map((p) => p.name)
  const unused = Object.keys(CONDITIONS).filter((k) => !rows.some((r) => r.key === k))
  return (
    <fieldset className="m-0 flex flex-col gap-2 rounded-2xl border-0 bg-sand p-4">
      <legend className="float-left mb-1 text-[15px] font-semibold">When does it apply?</legend>
      {rows.length === 0 && <p className="m-0 text-[14px] text-muted">{required ? 'Add at least one condition.' : 'Always, for this problem. Add conditions to narrow it down.'}</p>}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {rows.map((row, i) => (
          <ConditionRow
            key={row.key}
            row={row}
            names={names}
            products={products}
            onChange={(next) => setRows(rows.map((r, j) => (j === i ? next : r)))}
            onRemove={() => setRows(rows.filter((_, j) => j !== i))}
          />
        ))}
      </ul>
      {unused.length > 0 && (
        <label className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
          Add a condition
          <select value="" onChange={(e) => e.target.value && setRows([...rows, { key: e.target.value, value: '' }])} className={input}>
            <option value="">Choose…</option>
            {unused.map((k) => (
              <option key={k} value={k}>
                {CONDITIONS[k].label}
              </option>
            ))}
          </select>
        </label>
      )}
    </fieldset>
  )
}

const options = (map) => Object.entries(map).map(([value, label]) => ({ value, label }))

/** `rule` = the rule to change, or null for a new one. `kind` = 'resolution' | 'escalation'. */
export default function RuleEditor({ kind, rule, rules, onSaved, onClose }) {
  const names = useTaxonomy()
  const isNew = !rule
  const resolution = kind === 'resolution'
  const [form, setForm] = useState(() =>
    resolution
      ? {
          rule_id: rule?.rule_id || nextId(rules, 'RR'),
          description: rule?.description || '',
          subcategory: rule?.subcategory || '',
          department: rule?.department || '',
          urgency: rule?.urgency || 'Medium',
          priority: rule?.priority || 'P2',
          escalation_level: rule?.escalation_level || 'none',
          policy_id: rule?.policy_id || '',
          policy_section: rule?.policy_section || '',
          required_actions: (rule?.required_actions || []).join('\n'),
          prohibited_actions: (rule?.prohibited_actions || []).join('\n'),
          allowed_compensation: rule?.allowed_compensation || ['none'],
          follow_up_days: rule?.follow_up_days ?? 0,
        }
      : {
          rule_id: rule?.rule_id || nextId(rules, 'ESC'),
          name: rule?.name || '',
          description: rule?.description || '',
          escalation_level: rule?.escalation_level || 'supervisor',
          target_department: rule?.target_department || '',
          policy_id: rule?.policy_id || '',
          policy_section: rule?.policy_section || '',
        },
  )
  const [rows, setRows] = useState(() => toRows(rule?.conditions))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (key) => (value) => setForm({ ...form, [key]: value })
  const setFrom = (key) => (e) => set(key)(e.target.value)

  const teams = [...(names.taxonomy?.departments || [])].map((d) => ({ value: d.code, label: d.name }))
  const problems = (names.taxonomy?.categories || []).flatMap((c) => c.subcategories.map((s) => ({ value: s.code, label: `${c.name} — ${s.name}` })))
  const conditions = fromRows(rows)
  const missing = resolution ? !form.subcategory || !form.policy_id.trim() : form.name.trim().length < 3 || Object.keys(conditions).length === 0

  function toggleOffer(code) {
    const current = form.allowed_compensation.filter((c) => c !== 'none')
    const next = current.includes(code) ? current.filter((c) => c !== code) : [...current, code]
    set('allowed_compensation')(next.length ? next : ['none'])
  }

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = resolution
      ? {
          ...form,
          conditions,
          department: form.department || null,
          required_actions: lines(form.required_actions),
          prohibited_actions: lines(form.prohibited_actions),
          follow_up_days: Number(form.follow_up_days) || 0,
        }
      : { ...form, conditions, target_department: form.target_department || null }
    // When changing a rule, its ID and (for handling rules) its problem stay as they are.
    const changes = { ...body }
    delete changes.rule_id
    delete changes.subcategory
    try {
      if (isNew) await api.post(`/rules/${kind}`, body)
      else await api.patch(`/rules/${kind}/${body.rule_id}`, changes)
      onSaved(`Rule ${body.rule_id} was ${isNew ? 'added' : 'saved'}. It applies to new complaints straight away.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="form" onSubmit={save} className="flex flex-col gap-4 p-6" aria-label={isNew ? 'Add a rule' : `Change rule ${rule.rule_id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle>{isNew ? (resolution ? 'Add a handling rule' : 'Add an escalation rule') : `Change ${rule.rule_id}`}</SectionTitle>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className={fieldLabel}>
          Rule ID
          <input value={form.rule_id} onChange={(e) => set('rule_id')(e.target.value.toUpperCase())} disabled={!isNew} className={input} />
        </label>
        {resolution && isNew && <Select label="Problem" value={form.subcategory} onChange={set('subcategory')} options={[{ value: '', label: 'Choose…' }, ...problems]} />}
        {resolution && !isNew && (
          <p className={`${fieldLabel} m-0`}>
            Problem
            <span className="py-2 text-[15px] font-semibold text-ink">{names.subcategoryName(form.subcategory)}</span>
          </p>
        )}
        {!resolution && (
          <label className={fieldLabel}>
            Name
            <input value={form.name} onChange={setFrom('name')} placeholder="e.g. Legal threat" className={input} />
          </label>
        )}
      </div>

      <ConditionsBuilder rows={rows} setRows={setRows} required={!resolution} />

      {resolution ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Select label="Team" value={form.department} onChange={set('department')} options={[{ value: '', label: 'Problem’s usual team' }, ...teams]} />
            <Select label="Urgency" value={form.urgency} onChange={set('urgency')} options={URGENCY.map((u) => ({ value: u, label: u }))} />
            <Select label="Priority" value={form.priority} onChange={set('priority')} options={options(PRIORITY)} />
            <Select label="Escalate to" value={form.escalation_level} onChange={set('escalation_level')} options={options(ESCALATION)} />
          </div>
          <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
            <legend className="mb-1 text-[13px] text-muted">May offer</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {Object.entries(COMPENSATION)
                .filter(([code]) => code !== 'none')
                .map(([code, label]) => (
                  <label key={code} className="flex items-center gap-2 text-[15px]">
                    <input type="checkbox" checked={form.allowed_compensation.includes(code)} onChange={() => toggleOffer(code)} className="size-4 accent-forest" />
                    {label}
                  </label>
                ))}
            </div>
          </fieldset>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className={fieldLabel}>
              Must do (one per line)
              <textarea rows={3} value={form.required_actions} onChange={setFrom('required_actions')} className={input} />
            </label>
            <label className={fieldLabel}>
              Must not do (one per line)
              <textarea rows={3} value={form.prohibited_actions} onChange={setFrom('prohibited_actions')} className={input} />
            </label>
          </div>
        </>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Select label="Escalate to" value={form.escalation_level} onChange={set('escalation_level')} options={options(ESCALATION).filter((o) => o.value !== 'none')} />
          <Select label="Also send to team (optional)" value={form.target_department} onChange={set('target_department')} options={[{ value: '', label: 'No other team' }, ...teams]} />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <label className={fieldLabel}>
          Policy ID{resolution && ' *'}
          <input value={form.policy_id} onChange={(e) => set('policy_id')(e.target.value.toUpperCase())} placeholder="e.g. REF-POL" className={input} />
        </label>
        <label className={fieldLabel}>
          Section
          <input value={form.policy_section} onChange={setFrom('policy_section')} placeholder="e.g. 3.2" className={input} />
        </label>
        {resolution && (
          <label className={fieldLabel}>
            Follow up after (days)
            <input type="number" min="0" max="90" value={form.follow_up_days} onChange={setFrom('follow_up_days')} className={input} />
          </label>
        )}
        <label className={`${fieldLabel} ${resolution ? 'col-span-2 md:col-span-1' : 'col-span-2'}`}>
          Note (optional)
          <input value={form.description} onChange={setFrom('description')} className={input} />
        </label>
      </div>

      <ErrorNotice message={error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={busy || missing}>
          {busy ? 'Saving…' : isNew ? 'Add rule' : 'Save changes'}
        </Button>
        {missing && <span className="text-sm text-muted">{resolution ? 'Choose the problem and the policy it is based on.' : 'Give it a name and at least one condition.'}</span>}
      </div>
    </Card>
  )
}
