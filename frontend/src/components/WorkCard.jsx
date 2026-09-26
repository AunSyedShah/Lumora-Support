import { Link } from 'react-router-dom'

import { PRIORITY, PRIORITY_TONE, STAFF_STATUS } from '../lib/labels'
import { slaLine } from '../lib/sla'
import { useTaxonomy } from '../lib/taxonomy'
import { Badge } from './ui'

export default function WorkCard({ item, to, selected, children }) {
  const { subcategoryName } = useTaxonomy()
  const sla = slaLine(item.sla)
  return (
    <Link
      to={to}
      aria-current={selected ? 'page' : undefined}
      className={`flex flex-col gap-2 rounded-[20px] bg-white px-5 py-4 text-ink no-underline ${selected ? 'outline-2 outline-forest' : 'hover:bg-sand'}`}
    >
      <span className="flex items-start justify-between gap-3">
        <span className="text-base font-semibold">{item.title}</span>
        {item.priority && <Badge tone={PRIORITY_TONE[item.priority]}>{PRIORITY[item.priority]}</Badge>}
      </span>
      <span className="text-sm text-muted">
        {[item.complaint_id, subcategoryName(item.subcategory), STAFF_STATUS[item.status]].filter(Boolean).join(' · ')}
      </span>
      {(sla || children) && (
        <span className="flex flex-wrap items-center gap-2 text-sm">
          {sla && <Badge tone={sla.tone}>{sla.text}</Badge>}
          {children}
        </span>
      )}
    </Link>
  )
}
