import { useState } from 'react'
import { Link } from 'react-router-dom'

import Filters from '../../components/Filters'
import { Button, Card, ErrorNotice, Loading, PageTitle, SectionTitle } from '../../components/ui'
import { EMPTY_FILTERS, PERIODS, filterParams } from '../../lib/filters'
import { formatDate, lastDays } from '../../lib/format'
import { PRIORITY, SLA } from '../../lib/labels'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'

function Tile({ label, value, warn }) {
  return (
    <div className={`flex flex-col gap-1.5 rounded-[22px] px-5 py-5 ${warn ? 'bg-sun-soft text-sun-ink' : 'bg-white'}`}>
      <span className={`text-sm ${warn ? 'text-[#5a4300]' : 'text-muted'}`}>{label}</span>
      <span className="font-display text-[38px] leading-none font-bold">{value}</span>
    </div>
  )
}

/** One bar per day for the chosen period (days without complaints show as zero). */
function DailyBars({ volume, days }) {
  const counts = Object.fromEntries((volume || []).map((v) => [v.date, v.count]))
  const span = Number(days) || Math.max(14, (volume || []).length)
  const dates = lastDays(Math.min(span, 90))
  const max = Math.max(1, ...dates.map((d) => counts[d] || 0))
  const total = dates.reduce((sum, d) => sum + (counts[d] || 0), 0)
  return (
    <div className="flex flex-col gap-2">
      <div role="img" aria-label={`${total} new complaints over ${dates.length} days; the busiest day had ${max}.`} className="flex h-44 items-end gap-[3px] border-b-[1.5px] border-line">
        {dates.map((d) => (
          <span key={d} title={`${formatDate(d)}: ${counts[d] || 0}`} className="flex-1 rounded-t-md bg-forest" style={{ height: `${((counts[d] || 0) / max) * 100}%`, minHeight: counts[d] ? 3 : 0 }} />
        ))}
      </div>
      <div className="flex justify-between text-[13px] text-muted">
        <span>{formatDate(dates[0])}</span>
        <span>{formatDate(dates[dates.length - 1])}</span>
      </div>
    </div>
  )
}

function Distribution({ items, nameOf }) {
  const rows = (items || []).slice(0, 7)
  const max = Math.max(1, ...rows.map((r) => r.percent))
  return (
    <div className="grid grid-cols-[130px_minmax(0,1fr)_44px] items-center gap-x-3 gap-y-2.5 text-sm">
      {rows.map((r) => (
        <div key={r.value} className="contents">
          <span className="truncate">{r.value === 'unknown' ? 'Not sorted yet' : nameOf(r.value)}</span>
          <span className={`h-3 rounded-full ${r.value === 'unknown' ? 'bg-sage' : 'bg-forest'}`} style={{ width: `${(r.percent / max) * 100}%` }} />
          <span className="text-right">{Math.round(r.percent)}%</span>
        </div>
      ))}
    </div>
  )
}

/** Trend findings as plain sentences. */
function trendSentences(trends, names) {
  if (!trends) return []
  const label = (dimension, value) => {
    if (dimension === 'category') return names.categoryName(value)
    if (dimension === 'subcategory') return names.subcategoryName(value)
    if (dimension === 'department') return names.departmentName(value)
    return value
  }
  return [
    ...trends.rising.map((t) => `${label(t.dimension, t.value)}: ${t.current} complaints in the last ${trends.window_days} days${t.previous ? `, up from ${t.previous}` : ', none the week before'}.`),
    ...trends.recurring_product_issues.map((t) => `${t.product} came up in ${t.count_30_days} “${names.subcategoryName(t.subcategory)}” reports this month.`),
    ...trends.repeated_service_failures.map((t) => `${t.repeat_complaints} customers had to complain again about “${names.subcategoryName(t.subcategory)}”.`),
    ...trends.escalation_spikes.map((t) => `Unusually many escalations on ${formatDate(t.date)} (${t.escalations}).`),
  ]
}

export default function Overview() {
  const names = useTaxonomy()
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const params = filterParams(filters)
  const dashboard = useApi('/dashboard/admin', { params })
  const analytics = useApi('/analytics', { params })
  const trends = useApi('/analytics/trends', { params: filterParams({ ...filters, days: '' }) })

  const d = dashboard.data
  const a = analytics.data
  const period = PERIODS.find((p) => p.value === filters.days)?.label || 'All time'
  const sentences = trendSentences(trends.data, names).slice(0, 6)

  return (
    <div className="flex flex-col gap-5">
      <PageTitle eyebrow={`${period} · ${filters.department ? names.departmentName(filters.department) : 'all teams'}`} title="How support is doing">
        <Button variant="outline" to="/reports">
          Download a report
        </Button>
      </PageTitle>
      <Filters value={filters} onChange={setFilters} />
      <ErrorNotice message={dashboard.error || analytics.error} onRetry={() => (dashboard.reload(), analytics.reload())} />
      {!d && dashboard.loading && <Loading />}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Tile label="Open complaints" value={d.open} />
            <Tile label="Close to their deadline or late" value={d.sla_risks.at_risk + d.sla_risks.breached} warn={d.sla_risks.at_risk + d.sla_risks.breached > 0} />
            <Tile label="Waiting for a second look" value={d.manual_review.pending} />
            <Tile label="Resolved" value={a?.resolved_or_closed ?? '…'} />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <Card className="flex flex-col gap-4 p-6">
              <SectionTitle>New complaints per day</SectionTitle>
              {a ? <DailyBars volume={a.volume_by_day} days={filters.days} /> : <Loading />}
            </Card>
            <Card className="flex flex-col gap-4 p-6">
              <SectionTitle>What people complain about</SectionTitle>
              <Distribution items={d.category_distribution} nameOf={names.categoryName} />
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <section className="flex flex-col gap-3 rounded-[22px] bg-forest p-6 text-cream">
              <SectionTitle>Worth a look</SectionTitle>
              {sentences.length ? (
                <ul className="m-0 flex flex-col gap-2.5 pl-5 text-[15px] leading-snug">
                  {sentences.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              ) : (
                <p className="m-0 text-[15px] text-sage">Nothing unusual right now.</p>
              )}
            </section>
            <Card className="flex flex-col gap-3 p-6">
              <SectionTitle>Close to their deadline</SectionTitle>
              {d.sla_risks.most_urgent.length === 0 ? (
                <p className="m-0 text-[15px] text-muted">Everything is on time.</p>
              ) : (
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-[13px] text-muted">
                      <th scope="col" className="border-b border-line-soft py-2 pr-2 font-semibold">Complaint</th>
                      <th scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">Team</th>
                      <th scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">With</th>
                      <th scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">Priority</th>
                      <th scope="col" className="border-b border-line-soft py-2 pl-2 text-right font-semibold">State</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.sla_risks.most_urgent.map((r) => (
                      <tr key={r.complaint_id}>
                        <td className="border-b border-sand-2 py-2 pr-2">
                          <Link to={`/complaints/${r.complaint_id}`} className="font-semibold text-forest">
                            {r.complaint_id}
                          </Link>
                        </td>
                        <td className="border-b border-sand-2 px-2 py-2">{names.departmentName(r.department)}</td>
                        <td className="border-b border-sand-2 px-2 py-2">{r.assigned_to || 'Not assigned'}</td>
                        <td className="border-b border-sand-2 px-2 py-2">{PRIORITY[r.priority]}</td>
                        <td className={`border-b border-sand-2 py-2 pl-2 text-right font-semibold ${r.sla_resolution === 'breached' ? 'text-rust' : ''}`}>{SLA[r.sla_resolution]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
