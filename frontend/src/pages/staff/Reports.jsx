import { useState } from 'react'

import { downloadFile, errorMessage } from '../../api/client'
import Filters from '../../components/Filters'
import { Button, Card, ErrorNotice, Loading, PageTitle } from '../../components/ui'
import { EMPTY_FILTERS, filterParams } from '../../lib/filters'
import { useApi } from '../../lib/useApi'

// The API's report names, in plain words. Reports added later still show with their own title.
const ABOUT = {
  complaint_intelligence: ['Complaint insights', 'The big picture: what people complain about, routing, escalations, repeat complaints, reply times and policy use.'],
  complaint_analysis: ['All complaints', 'Every complaint with its problem type, priority, status and outcome.'],
  department_performance: ['How each team is doing', 'Volume, reply times and resolution times per team.'],
  sla_status: ['Reply and resolution times', 'Which complaints were handled on time, and which are close or late.'],
  escalations: ['Escalations', 'Escalated complaints, to whom, and why.'],
  manual_reviews: ['Second looks', 'Complaints a person checked, why they were flagged and what was decided.'],
  genai_python_comparison: ['Suggestions vs. our policies', 'Where the automatic suggestion and our policy checks disagreed, field by field.'],
  resolution_compliance: ['Did we follow our policies?', 'Whether each resolution included the required steps and avoided forbidden ones.'],
  policy_usage: ['Policies in use', 'How often each policy section was the basis for a resolution.'],
}

const FORMATS = [
  ['csv', 'CSV'],
  ['xlsx', 'Excel'],
  ['pdf', 'PDF'],
]

export default function Reports() {
  const reports = useApi('/reports')
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS, days: '30' })
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function download(name, format) {
    setBusy(`${name}-${format}`)
    setError('')
    try {
      await downloadFile(`/reports/${name}`, { ...filterParams(filters), format }, `${name}.${format}`)
    } catch (e) {
      setError(errorMessage(e, 'The report could not be created. Please try again.'))
    } finally {
      setBusy('')
    }
  }

  const ordered = [...(reports.data || [])].sort((a, b) => (Object.keys(ABOUT).indexOf(a.name) + 1 || 99) - (Object.keys(ABOUT).indexOf(b.name) + 1 || 99))

  return (
    <div className="flex flex-col gap-5">
      <PageTitle eyebrow="Choose the period and filters, then download in the format you need" title="Reports" />
      <Filters value={filters} onChange={setFilters} />
      <ErrorNotice message={error || reports.error} onRetry={reports.error ? reports.reload : undefined} />
      {reports.loading && !reports.data && <Loading />}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {ordered.map((r) => {
          const [title, description] = ABOUT[r.name] || [r.title, '']
          return (
            <Card key={r.name} as="article" className="flex flex-col gap-3 p-6">
              <h2 className="m-0 font-display text-xl font-bold">{title}</h2>
              {description && <p className="m-0 flex-1 text-[15px] leading-relaxed text-muted">{description}</p>}
              <div className="flex flex-wrap gap-2">
                {FORMATS.map(([format, label]) => (
                  <Button key={format} variant="light" disabled={Boolean(busy)} onClick={() => download(r.name, format)} aria-label={`Download ${title} as ${label}`}>
                    {busy === `${r.name}-${format}` ? 'Preparing…' : label}
                  </Button>
                ))}
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
