import { Button, Card, ErrorNotice, Loading, SectionTitle } from '../../components/ui'
import { useApi } from '../../lib/useApi'

// The fields our rules compare with the automatic suggestion, in plain words.
const FIELDS = [
  ['category', 'Problem type'],
  ['subcategory', 'Exact problem'],
  ['department', 'Team'],
  ['urgency', 'Urgency'],
  ['priority', 'Priority'],
  ['escalation', 'Escalation'],
]

const percent = (part, total) => (total ? Math.round((part / total) * 100) : 0)

/** How often the automatic suggestion matched what our policies say (latest check per complaint). */
export default function Agreement() {
  const rows = useApi('/validation/comparison')
  const list = rows.data || []
  const total = list.length
  const allMatch = list.filter((r) => r.match === 'match').length
  const secondLook = list.filter((r) => r.verification_status === 'manual_review').length

  return (
    <Card className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <SectionTitle>Suggestions vs. our policies</SectionTitle>
          <p className="m-0 text-[15px] text-muted">Every suggestion is checked against our rules before anyone acts on it. All complaints checked so far.</p>
        </div>
        <Button variant="light" to="/reports">
          See each complaint
        </Button>
      </div>
      <ErrorNotice message={rows.error} onRetry={rows.reload} />
      {rows.loading && !rows.data && <Loading />}
      {rows.data && total === 0 && <p className="m-0 text-muted">No complaints have been checked yet.</p>}
      {total > 0 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
          <div className="flex flex-col gap-3">
            <p className="m-0">
              <span className="font-display text-[44px] leading-none font-bold text-forest">{percent(allMatch, total)}%</span>
              <span className="mt-1 block text-[15px] text-muted">
                matched our policies on everything ({allMatch} of {total})
              </span>
            </p>
            <p className="m-0 text-[15px]">
              <strong>{secondLook}</strong> <span className="text-muted">({percent(secondLook, total)}%) were given to a person for a second look.</span>
            </p>
          </div>
          <div className="grid grid-cols-[110px_minmax(0,1fr)_44px] items-center gap-x-3 gap-y-2.5 text-sm">
            {FIELDS.map(([field, label]) => {
              const agreed = percent(list.filter((r) => !r.mismatched_fields.includes(field)).length, total)
              return (
                <div key={field} className="contents">
                  <span>{label}</span>
                  <span className="h-3 overflow-hidden rounded-full bg-sand-2" role="img" aria-label={`${label}: agreed ${agreed}%`}>
                    <span className="block h-full rounded-full bg-forest" style={{ width: `${agreed}%` }} />
                  </span>
                  <span className="text-right">{agreed}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </Card>
  )
}
