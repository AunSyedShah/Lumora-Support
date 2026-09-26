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

/** Plain text for people: no rule ids, and policy codes ("INS-POL 4.3") replaced by their names. */
export function plainText(text, policyName) {
  return (text || '').replace(RULE_TAG, '').replace(POLICY_REF, (match, docId, section) => {
    if (/^(ORD|CMP)$/.test(docId.split('-')[0])) return match
    return policyName(section ? `${docId} ${section}` : docId)
  })
}
