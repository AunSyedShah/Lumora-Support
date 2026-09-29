/*
 * Plain-language labels. The API uses internal codes (P1, department_manager, awaiting_customer...);
 * people see words. No screen should show GenAI / Python / rule-matrix vocabulary.
 */

export const PRIORITY = { P0: 'Urgent', P1: 'High', P2: 'Medium', P3: 'Low' }
export const PRIORITY_TONE = { P0: 'warn', P1: 'sun', P2: 'outline', P3: 'sand' }

export const STAFF_STATUS = {
  new: 'New',
  analyzed: 'Ready',
  assigned: 'Assigned',
  in_progress: 'In progress',
  awaiting_customer: 'Waiting on customer',
  escalated: 'Escalated',
  resolved: 'Resolved',
  closed: 'Closed',
  reopened: 'Reopened',
}

// What the customer sees (the API also sends `resolution_status` in the same words).
export const CUSTOMER_STATUS = {
  new: 'Received',
  analyzed: 'Received',
  assigned: 'Being handled',
  in_progress: 'Being handled',
  awaiting_customer: 'We need something from you',
  escalated: 'With a specialist team',
  resolved: 'Resolved',
  closed: 'Closed',
  reopened: 'Reopened',
}
export const CUSTOMER_STATUS_TONE = {
  awaiting_customer: 'sun',
  resolved: 'sand',
  closed: 'sand',
}

export const ESCALATION = {
  none: 'No one',
  supervisor: 'Supervisor',
  department_manager: 'Department manager',
  specialist_team: 'Specialist team',
  compliance_review: 'Compliance team',
  critical_management: 'Senior management',
}

export const COMPENSATION = {
  none: 'Nothing extra',
  full_refund: 'Full refund',
  partial_refund: 'Partial refund',
  shipping_fee_refund: 'Shipping fee refund',
  fee_waiver: 'Fee waived',
  replacement: 'Replacement',
  repair: 'Repair',
  subscription_credit: 'Subscription credit',
}

export const CHANNEL = { web: 'Website', email: 'Email', chat: 'Chat', upload: 'Uploaded file' }
export const CONTACT = { email: 'Email', phone: 'Phone', chat: 'Chat' }
export const CUSTOMER_TYPE = { standard: 'Customer', premium: 'Premium member', business: 'Business customer' }
export const ROLE = { customer: 'Customer', agent: 'Support agent', reviewer: 'Reviewer', manager: 'Manager', admin: 'Administrator' }

export const SLA = {
  on_track: 'On time',
  at_risk: 'Running out of time',
  breached: 'Overdue',
  met: 'Done in time',
  missed: 'Done late',
  paused: 'Paused (waiting on customer)',
}
export const SLA_TONE = { at_risk: 'sun', breached: 'warn', missed: 'warn' }

// Sentiment (SRS Step 17) in everyday words. It shapes the tone of the reply, never the priority.
export const SENTIMENT = { Positive: 'Positive', Neutral: 'Calm', Negative: 'Unhappy', 'Strongly Negative': 'Very unhappy' }
export const SENTIMENT_TONE = { Negative: 'soft', 'Strongly Negative': 'warn' }

/*
 * Why a complaint needs a second look. The API returns sentences written for developers
 * ("Critical finding (escalation): ..."), so they are recognised by their wording and replaced.
 */
const CHECK_REASON = {
  escalation: 'The suggested plan missed a required escalation',
  compensation: 'The suggestion offered something our policies don’t allow',
  prohibited_action: 'The suggested reply does something our policies forbid',
  unsupported_promise: 'The reply promises something we can’t guarantee',
  hallucinated_fact: 'The suggestion mentions facts we couldn’t find',
  hallucinated_reference: 'The suggestion refers to a policy we don’t have',
  category: 'The suggestion and our policies disagree on what the problem is',
  urgency: 'The suggestion and our policies disagree on how urgent it is',
  priority: 'The suggestion and our policies disagree on how urgent it is',
  department: 'The suggestion and our policies disagree on which team should handle it',
}

export function reviewReason(text) {
  const t = text.toLowerCase()
  const critical = /critical finding \(([a-z_]+)\)/.exec(t)
  if (critical) return CHECK_REASON[critical[1]] || 'The suggestion broke one of our policies'
  if (t.includes('verification score')) return 'Several details didn’t match our policies'
  if (t.includes('ambiguous')) return 'It isn’t clear what the problem is'
  if (t.includes('eligibility unclear')) return 'Details are missing to decide what the customer is entitled to'
  if (t.includes('policy support is missing')) return 'No policy clearly covers this case'
  if (t.includes('policy contradiction')) return 'It relied on an older or lower-ranked document'
  if (t.includes('sensitive complaint')) return 'Safety, security and privacy cases are always checked by a person'
  if (t.includes('manipulation')) return 'The message tries to give our system instructions'
  if (t.includes('processing failed')) return 'Automatic handling didn’t work — handle it by hand'
  if (t.includes('could not be produced')) return 'No suggestion could be made — handle it by hand'
  return text
}

export function reviewReasons(list = []) {
  return [...new Set(list.map(reviewReason))]
}

/** "department_manager" -> "Department manager" for anything not in a map above. */
export function humanize(code) {
  if (!code) return ''
  return code.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())
}

// Timeline (audit log) entries.
export const AUDIT = {
  submitted: 'Complaint received',
  processed: 'Checked and routed automatically',
  status_changed: 'Status changed',
  assigned: 'Assigned',
  approved: 'Approved after a second look',
  rejected: 'Sent back after a second look',
  modified: 'Plan edited',
  reclassified: 'Problem type changed',
  escalated: 'Escalated',
  regenerated: 'New suggestion made',
  commented: 'Note added',
  response_sent: 'Reply sent to the customer',
  follow_up_done: 'Follow-up done',
  customer_reply: 'Customer replied',
  reopened: 'Reopened by the customer',
}

// Status changes staff can make from each status (mirrors workflow/lifecycle.py; the API has the final say).
// "escalated" and "assigned" have their own actions, so they are not offered here.
export const NEXT_STATUS = {
  new: ['in_progress', 'closed'],
  analyzed: ['in_progress', 'awaiting_customer', 'resolved', 'closed'],
  assigned: ['in_progress', 'awaiting_customer', 'resolved'],
  in_progress: ['awaiting_customer', 'resolved'],
  awaiting_customer: ['in_progress', 'resolved', 'closed'],
  escalated: ['in_progress', 'awaiting_customer', 'resolved'],
  resolved: ['closed'],
  closed: [],
  reopened: ['in_progress', 'awaiting_customer', 'resolved'],
}
export const STATUS_ACTION = {
  in_progress: 'Start working on it',
  awaiting_customer: 'Waiting on customer',
  resolved: 'Mark resolved',
  closed: 'Close',
}

/** The API's "contains unsupported content (...)" refusal, in plain words, with the quoted parts. */
export function replyProblem(message) {
  if (!message?.includes('unsupported content')) return null
  const quotes = [...message.matchAll(/"([^"]+)"/g)].map((m) => m[1])
  return { text: 'Your reply says something our policies don’t allow. Please change these parts before sending:', quotes }
}
