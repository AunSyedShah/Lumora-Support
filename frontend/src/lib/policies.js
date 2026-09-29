import { useApi } from './useApi'

/** "DEL-POL 2.2" -> "Delivery Policy, section 2.2" using the live knowledge base. */
export function usePolicyNames() {
  const docs = useApi('/kb/documents', { params: { usable_only: true } })
  const titles = {}
  for (const d of docs.data || []) titles[d.doc_id] = d.title.replace(/^Lumora Home Technologies\s*[-–]\s*/, '')
  return (reference) => {
    if (!reference) return ''
    const [docId, section] = reference.split(' ')
    const title = titles[docId] || docId
    return section ? `${title}, section ${section}` : title
  }
}

const RULE_TAG = /^\s*\[Required by [A-Z]+-\d+\]\s*/i
const POLICY_REF = /\b([A-Z]{2,6}-[A-Z]{2,6})(?:\s+(\d+(?:\.\d+)*))?\b/g
// Priority codes in suggested text ("a P0 safety case") read as words ("an urgent safety case").
const PRIORITY_WORDS = { P0: 'urgent', P1: 'high-priority', P2: 'medium-priority', P3: 'low-priority' }

/** Plain text for people: no rule ids, policy codes ("INS-POL 4.3") replaced by their names, no priority codes. */
export function plainText(text, policyName) {
  return (text || '')
    .replace(RULE_TAG, '')
    .replace(POLICY_REF, (match, docId, section) => {
      if (/^(ORD|CMP)$/.test(docId.split('-')[0])) return match
      return policyName(section ? `${docId} ${section}` : docId)
    })
    .replace(/\b(an?) (P[0-3])\b/g, (match, article, code) => `${code === 'P0' ? 'an' : 'a'} ${PRIORITY_WORDS[code]}`)
    .replace(/\bP[0-3]\b/g, (code) => PRIORITY_WORDS[code])
}
