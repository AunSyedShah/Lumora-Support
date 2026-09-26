import { timeLeft } from './format'
import { SLA, SLA_TONE } from './labels'

/** The SLA line on a staff card: the deadline that matters now and how much time is left. */
export function slaLine(sla) {
  if (!sla) return null
  if (sla.paused) return { text: SLA.paused, tone: 'sand' }
  // Some endpoints only send the resolution deadline; then that is the one shown.
  const replyPending = ['on_track', 'at_risk', 'breached'].includes(sla.response) && Boolean(sla.response_due)
  const state = replyPending ? sla.response : sla.resolution
  const due = replyPending ? sla.response_due : sla.resolution_due
  if (!due || !['on_track', 'at_risk', 'breached'].includes(state)) return null
  const left = timeLeft(due)
  const text = left.startsWith('overdue') ? `${replyPending ? 'Reply' : 'Resolution'} ${left}` : `${replyPending ? 'Reply' : 'Resolve'} within ${left}`
  return { text, tone: SLA_TONE[state] || 'green' }
}
