import { CHANNEL, PRIORITY } from '../lib/labels'
import { useTaxonomy } from '../lib/taxonomy'
import { PERIODS } from '../lib/filters'
import { Select } from './ui'

export default function Filters({ value, onChange, showPeriod = true }) {
  const { taxonomy } = useTaxonomy()
  const set = (key) => (v) => onChange({ ...value, [key]: v })
  return (
    <form aria-label="Filters" className="flex flex-wrap gap-2.5" onSubmit={(e) => e.preventDefault()}>
      {showPeriod && <Select label="Dates" value={value.days} onChange={set('days')} options={PERIODS} />}
      <Select label="Team" value={value.department} onChange={set('department')} options={[{ value: '', label: 'All teams' }, ...(taxonomy?.departments || []).map((d) => ({ value: d.code, label: d.name }))]} />
      <Select label="Problem type" value={value.category} onChange={set('category')} options={[{ value: '', label: 'All types' }, ...(taxonomy?.categories || []).map((c) => ({ value: c.code, label: c.name }))]} />
      <Select label="Priority" value={value.priority} onChange={set('priority')} options={[{ value: '', label: 'Any' }, ...Object.entries(PRIORITY).map(([v, label]) => ({ value: v, label }))]} />
      <Select label="Came in by" value={value.channel} onChange={set('channel')} options={[{ value: '', label: 'Any channel' }, ...Object.entries(CHANNEL).map(([v, label]) => ({ value: v, label }))]} />
    </form>
  )
}
