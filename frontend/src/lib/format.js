const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
const dateFormat = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const timeFormat = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' })

const UNITS = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

/** "2 hours ago", "in 3 days". */
export function timeAgo(value) {
  if (!value) return ''
  const seconds = (new Date(value) - Date.now()) / 1000
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit)
  }
  return 'just now'
}

/** "3 h 10 min" left until a deadline (or "overdue by 2 h"). */
export function timeLeft(value) {
  if (!value) return ''
  const minutes = Math.round((new Date(value) - Date.now()) / 60000)
  const text = (m) => {
    const abs = Math.abs(m)
    if (abs >= 48 * 60) return `${Math.round(abs / 1440)} days`
    if (abs >= 60) return `${Math.floor(abs / 60)} h ${abs % 60} min`
    return `${abs} min`
  }
  return minutes >= 0 ? text(minutes) : `overdue by ${text(minutes)}`
}

export const formatDate = (value) => (value ? dateFormat.format(new Date(value)) : '')
export const formatDateTime = (value) => (value ? dateTimeFormat.format(new Date(value)) : '')
export const formatTime = (value) => (value ? timeFormat.format(new Date(value)) : '')

export function money(amount) {
  if (amount === null || amount === undefined) return ''
  return `${Number(amount).toFixed(2)} USD`
}

export function initials(name = '') {
  const parts = name.replace(/[_.]/g, ' ').trim().split(/\s+/)
  return (parts[0]?.[0] || '?').toUpperCase() + (parts[1]?.[0] || '').toUpperCase()
}

/** The last `count` dates as "YYYY-MM-DD", oldest first (for per-day charts). */
export function lastDays(count) {
  const now = Date.now()
  return Array.from({ length: count }, (_, i) => new Date(now - (count - 1 - i) * 24 * 3600 * 1000).toISOString().slice(0, 10))
}
