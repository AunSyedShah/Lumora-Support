import { useState } from 'react'
import { Link } from 'react-router-dom'

import Filters from '../../components/Filters'
import { Button, Card, ErrorNotice, Loading, PageTitle, SectionTitle } from '../../components/ui'
import { EMPTY_FILTERS, PERIODS, filterParams } from '../../lib/filters'
import { formatDate, lastDays } from '../../lib/format'
import { ESCALATION, PRIORITY, SENTIMENT, SLA } from '../../lib/labels'
import { useTaxonomy } from '../../lib/taxonomy'
import { useApi } from '../../lib/useApi'
import Agreement from './Agreement'

/** "Reply overdue", "Reply due soon", or the resolution state. */
function deadlineText(row) {
  if (row.deadline_kind === 'reply') return row.deadline_state === 'breached' ? 'Reply overdue' : 'Reply due soon'
  return SLA[row.deadline_state] || SLA[row.sla_resolution]
}

/** A number that also leads to the complaints behind it. */
function Tile({ label, value, warn, to }) {
  const colours = warn ? 'bg-sun-soft text-sun-ink hover:bg-sun' : 'bg-white text-ink hover:bg-sand'
  const content = (
    <>
      <span className={`text-sm ${warn ? 'text-[#5a4300]' : 'text-muted'}`}>{label}</span>
      <span className="font-display text-[38px] leading-none font-bold">{value}</span>
      <span className="text-[13px] underline underline-offset-4 opacity-70">See them</span>
    </>
  )
  const className = `flex flex-col gap-1.5 rounded-[22px] px-5 py-5 no-underline ${colours}`
  return to.startsWith('#') ? (
    <a href={to} className={className}>
      {content}
    </a>
  ) : (
    <Link to={to} className={className}>
      {content}
    </Link>
  )
}

/** Per team: open work, late work and how often deadlines were met. */
function Teams({ teams, departmentName }) {
  if (!teams?.length) return null
  return (
    <Card className="flex min-w-0 flex-col gap-3 p-6">
      <SectionTitle>How each team is doing</SectionTitle>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <thead>
            <tr className="text-left text-[13px] text-muted">
              {['Team', 'Open', 'Late', 'Solved on time', 'Average time to solve'].map((h) => (
                <th key={h} scope="col" className="border-b border-line-soft px-2 py-2 font-semibold first:pl-0">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {teams.map((t) => (
              <tr key={t.department}>
                <td className="border-b border-sand-2 py-2 pr-2">
                  <Link to={`/complaints?department=${t.department}&show=open`} className="font-semibold text-forest">
                    {departmentName(t.department)}
                  </Link>
                </td>
                <td className="border-b border-sand-2 px-2 py-2">{t.open}</td>
                <td className={`border-b border-sand-2 px-2 py-2 ${t.sla_breached_open ? 'font-semibold text-rust' : ''}`}>{t.sla_breached_open}</td>
                <td className="border-b border-sand-2 px-2 py-2">{t.sla_met_percent == null ? '—' : `${Math.round(t.sla_met_percent)}%`}</td>
                <td className="border-b border-sand-2 px-2 py-2">{t.avg_resolution_hours == null ? '—' : t.avg_resolution_hours < 1 ? 'under 1 h' : `${Math.round(t.avg_resolution_hours)} h`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
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

const PRIORITY_ORDER = ['P0', 'P1', 'P2', 'P3', 'unknown']
const SENTIMENT_ORDER = ['Strongly Negative', 'Negative', 'Neutral', 'Positive', 'unknown']
const inOrder = (items, order) => [...(items || [])].sort((a, b) => order.indexOf(a.value) - order.indexOf(b.value))

/** Priority, mood and escalations side by side (SRS Step 63). Mood is shown next to priority, not mixed into it. */
function Breakdown({ d }) {
  const esc = d.escalations
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="flex min-w-0 flex-col gap-4 p-6">
        <SectionTitle>How urgent</SectionTitle>
        <Distribution items={inOrder(d.priority_levels, PRIORITY_ORDER)} nameOf={(v) => PRIORITY[v] || v} />
      </Card>
      <Card className="flex min-w-0 flex-col gap-4 p-6">
        <SectionTitle>How customers feel</SectionTitle>
        <Distribution items={inOrder(d.sentiment_distribution, SENTIMENT_ORDER)} nameOf={(v) => SENTIMENT[v] || v} />
        <p className="m-0 text-[13px] text-muted">Mood guides the tone of replies. Priority comes from our rules, not from how upset someone is.</p>
      </Card>
      <Card className="flex min-w-0 flex-col gap-4 p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <SectionTitle>Escalations</SectionTitle>
          <Link to="/complaints?show=escalated" className="text-[15px] font-semibold text-forest">
            {esc.total} in total · {esc.open} open
          </Link>
        </div>
        {esc.by_level.length ? (
          <Distribution items={esc.by_level} nameOf={(v) => ESCALATION[v] || v} />
        ) : (
          <p className="m-0 text-[15px] text-muted">No escalations in this period.</p>
        )}
      </Card>
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
            <Tile label="Open complaints" value={d.open} to="/complaints?show=open" />
            <Tile label="Close to their deadline or late" value={d.sla_risks.at_risk + d.sla_risks.breached} warn={d.sla_risks.at_risk + d.sla_risks.breached > 0} to="#deadlines" />
            <Tile label="Waiting for a second look" value={d.manual_review.pending} to="/review" />
            <Tile label="Resolved" value={a?.resolved_or_closed ?? '…'} to="/complaints?status=resolved" />
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

          <Breakdown d={d} />

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
            <Card id="deadlines" className="flex min-w-0 flex-col gap-3 p-6 scroll-mt-6">
              <SectionTitle>Close to their deadline</SectionTitle>
              {d.sla_risks.most_urgent.length === 0 ? (
                <p className="m-0 text-[15px] text-muted">Everything is on time.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[420px] border-collapse text-sm">
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
                              {r.title || r.complaint_id}
                            </Link>
                            <div className="text-[12px] text-muted">{r.complaint_id}</div>
                          </td>
                          <td className="border-b border-sand-2 px-2 py-2">{names.departmentName(r.department)}</td>
                          <td className="border-b border-sand-2 px-2 py-2">{r.assigned_to_name || r.assigned_to || 'Not assigned'}</td>
                          <td className="border-b border-sand-2 px-2 py-2">{PRIORITY[r.priority]}</td>
                          <td className={`border-b border-sand-2 py-2 pl-2 text-right font-semibold ${r.deadline_state === 'breached' ? 'text-rust' : ''}`}>{deadlineText(r)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>

          <Teams teams={d.teams} departmentName={names.departmentName} />
          <Agreement />
        </>
      )}
    </div>
  )
}
