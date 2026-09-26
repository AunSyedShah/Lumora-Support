export const PERIODS = [
  { value: '7', label: 'Last 7 days' },
  { value: '14', label: 'Last 14 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
  { value: '', label: 'All time' },
]

/** The same filters on the overview, reports and complaint list: dates, team, problem type, priority, channel. */
export function filterParams(filters) {
  const params = {}
  if (filters.days) {
    const from = new Date(Date.now() - Number(filters.days) * 24 * 3600 * 1000)
    params.date_from = from.toISOString().slice(0, 10)
  }
  for (const key of ['department', 'category', 'priority', 'channel']) if (filters[key]) params[key] = filters[key]
  return params
}

export const EMPTY_FILTERS = { days: '14', department: '', category: '', priority: '', channel: '' }
