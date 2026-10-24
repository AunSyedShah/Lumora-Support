import { AlertIcon, CheckIcon } from '../../../components/icons'
import { Badge, Card, SectionTitle } from '../../../components/ui'
import { ESCALATION, PRIORITY } from '../../../lib/labels'
import { useTaxonomy } from '../../../lib/taxonomy'
import { useApi } from '../../../lib/useApi'

// The checks Python runs, in everyday words.
const CHECK = {
  schema_validation: 'Answer format',
  category: 'Problem type',
  subcategory: 'Exact problem',
  secondary_issues: 'Other problems mentioned',
  department: 'Team',
  supporting_departments: 'Helping teams',
  urgency: 'Urgency',
  priority: 'Priority',
  escalation: 'Escalation',
  compensation: 'Refund or compensation',
  compensation_not_offered: 'Refund or compensation',
  follow_up: 'Follow-up',
  policy_applicability: 'Policy used',
  policy_support: 'Policy support',
  policy_precedence: 'Which policy wins',
  required_actions: 'Required steps',
  missing_required_action: 'Required step missing',
  prohibited_action: 'Forbidden action',
  unsupported_promise: 'Promise not backed by policy',
  hallucinated_reference: 'Invented policy reference',
  hallucinated_fact: 'Invented fact',
  consistency: 'Consistency',
}
const SEVERITY = { critical: ['Serious', 'warn'], major: ['Important', 'sun'], minor: ['Small', 'sand'] }
const checkName = (name) => CHECK[name] || name.replace(/_/g, ' ')

/** Turn codes inside a sentence into names: ['CUSTOMER_RELATIONS'] -> Customer Relations, SMART_PLUG -> Smart Plug. */
function plain(text, names) {
  return String(text)
    .replace(/\[([^\]]*)\]/g, (_, inner) => inner.replace(/['"]/g, ''))
    .replace(/\b[A-Z]+(?:_[A-Z]+)+\b/g, (code) => names.departmentName(code) || code)
}

const CHANGED = { department: 'Team', priority: 'Priority', urgency: 'Urgency', escalation: 'Escalate to', category: 'Problem type', subcategory: 'Exact problem' }

/** "escalation none -> supervisor (mandatory escalation rules)" -> "Escalate to: No one -> Supervisor (mandatory escalation rules)" */
function change(text, names) {
  const m = /^(department|priority|urgency|escalation|category|subcategory) (\S+) -> (\S+)(?: \((.*)\))?$/.exec(text)
  if (!m) return plain(text.charAt(0).toUpperCase() + text.slice(1), names)
  const [, field, from, to, why] = m
  const show = { department: names.departmentName, priority: (v) => PRIORITY[v] || v, escalation: (v) => ESCALATION[v] || v, category: names.categoryName, subcategory: names.subcategoryName }[field] || ((v) => v)
  return `${CHANGED[field]}: ${show(from)} → ${show(to)}${why ? ` (${plain(why, names)})` : ''}`
}

function Row({ label, ai, rules, same }) {
  return (
    <tr className={same ? '' : 'bg-sun-soft'}>
      <th scope="row" className="border-b border-sand-2 py-2 pr-2 pl-2 text-left font-semibold">
        {label}
      </th>
      <td className="border-b border-sand-2 px-2 py-2">{ai}</td>
      <td className={`border-b border-sand-2 px-2 py-2 ${same ? '' : 'font-semibold'}`}>{rules}</td>
      <td className="border-b border-sand-2 py-2 pr-2 text-right">
        <span className={same ? 'text-forest' : 'text-rust'} title={same ? 'Same' : 'Different: our rules decide'}>
          {same ? <CheckIcon size={18} /> : <AlertIcon size={18} />}
          <span className="sr-only">{same ? 'Same' : 'Different'}</span>
        </span>
      </td>
    </tr>
  )
}

/** "Checked by our rules": what the AI said, what the rule matrix says, what was changed and what was found. */
export default function Validation({ complaintId, refreshKey }) {
  const names = useTaxonomy()
  const result = useApi(`/validation/complaints/${complaintId}/latest`, { params: { v: refreshKey } })
  const v = result.data
  if (!v) return null
  const c = v.comparison
  const dash = (x) => x || '—'
  const rows = [
    ['Problem type', names.categoryName(c.genai_category), names.categoryName(c.python_category), c.genai_category === c.python_category],
    ['Exact problem', names.subcategoryName(c.genai_subcategory), names.subcategoryName(c.python_subcategory), c.genai_subcategory === c.python_subcategory],
    ['Team', names.departmentName(c.genai_department), names.departmentName(c.python_department), c.genai_department === c.python_department],
    ['Urgency', c.genai_urgency, c.python_urgency, c.genai_urgency === c.python_urgency],
    ['Priority', PRIORITY[c.genai_priority], PRIORITY[c.python_priority], c.genai_priority === c.python_priority],
    ['Escalate to', ESCALATION[c.genai_escalation], ESCALATION[c.python_escalation], c.genai_escalation === c.python_escalation],
  ]
  const problems = v.checks.filter((k) => k.status === 'fail' || k.status === 'warning')
  const passed = v.checks.filter((k) => k.status === 'pass')
  const changes = v.final_resolution?.enforced || []
  const needsPerson = v.decision === 'manual_review'

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle>Checked by our rules</SectionTitle>
        <Badge tone={needsPerson ? 'soft' : 'green'}>
          {needsPerson ? 'Needs a person' : 'Verified'} · {v.score}/100
        </Badge>
      </div>
      <p className="m-0 text-[14px] leading-snug text-muted">
        {v.genai_available
          ? 'The AI’s suggestion was compared with our rule matrix, field by field. Where they differ, our rules decide.'
          : 'The AI could not answer, so our rules decided on their own.'}
      </p>

      {v.genai_available && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[300px] border-collapse text-[14px]">
            <thead>
              <tr className="text-left text-[12px] text-muted">
                <th scope="col" className="border-b border-line-soft py-1.5 pl-2 font-semibold">
                  <span className="sr-only">Field</span>
                </th>
                <th scope="col" className="border-b border-line-soft px-2 py-1.5 font-semibold">
                  AI said
                </th>
                <th scope="col" className="border-b border-line-soft px-2 py-1.5 font-semibold">
                  Our rules say
                </th>
                <th scope="col" className="border-b border-line-soft py-1.5 pr-2 font-semibold">
                  <span className="sr-only">Same or different</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, ai, rules, same]) => (
                <Row key={label} label={label} ai={dash(ai)} rules={rules || 'Could not tell'} same={same} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {changes.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <h3 className="m-0 text-[15px] font-semibold">What our rules changed</h3>
          <ul className="m-0 flex flex-col gap-1 pl-5 text-[14px]">
            {changes.map((x) => (
              <li key={x}>{change(x, names)}</li>
            ))}
          </ul>
        </div>
      )}

      {problems.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="m-0 text-[15px] font-semibold">What was found ({problems.length})</h3>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {problems.map((k, i) => {
              const [label, tone] = SEVERITY[k.severity] || ['Note', 'sand']
              return (
                <li key={`${k.name}-${i}`} className="flex flex-col gap-0.5 rounded-xl bg-sand px-3 py-2 text-[14px]">
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge tone={tone}>{label}</Badge>
                    <strong>{checkName(k.name)}</strong>
                  </span>
                  <span className="text-muted">{plain(k.message, names)}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      {problems.length === 0 && v.genai_available && <p className="m-0 text-[14px] font-semibold text-forest">No problems found in the AI’s answer.</p>}

      {passed.length > 0 && (
        <details className="rounded-xl bg-sand px-4 py-2.5">
          <summary className="cursor-pointer text-[14px] font-semibold">{passed.length} checks passed</summary>
          <ul className="m-0 mt-2 flex flex-wrap gap-x-4 gap-y-1 pl-5 text-[14px] text-muted">
            {[...new Set(passed.map((k) => checkName(k.name)))].map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  )
}
