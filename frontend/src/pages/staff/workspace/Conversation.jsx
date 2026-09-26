import { PaperclipIcon } from '../../../components/icons'
import { formatDateTime, initials } from '../../../lib/format'
import { CUSTOMER_TYPE } from '../../../lib/labels'

export function Bubble({ fromCustomer, name, at, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm text-muted">
        <strong className="text-ink">{name}</strong> · {formatDateTime(at)}
      </span>
      <p className={`m-0 px-5 py-3.5 text-base leading-relaxed whitespace-pre-line ${fromCustomer ? 'rounded-[4px_18px_18px_18px] bg-sand' : 'rounded-[18px_4px_18px_18px] bg-mint'}`}>{children}</p>
    </div>
  )
}

/** The customer's complaint and every message since, as the customer sees them. */
export default function Conversation({ complaint }) {
  const customerLabel = `${complaint.customer} · ${CUSTOMER_TYPE[complaint.customer_type] || 'Customer'}`
  return (
    <div className="flex gap-3.5">
      <div aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-full bg-mint font-semibold text-forest">
        {initials(complaint.customer)}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <Bubble fromCustomer name={customerLabel} at={complaint.created_at}>
          {complaint.description}
          {complaint.supporting_information && `\n\n${complaint.supporting_information}`}
        </Bubble>
        {complaint.messages.map((m) => (
          <Bubble key={`${m.at}-${m.text.slice(0, 16)}`} fromCustomer={m.sender === 'customer'} name={m.sender === 'customer' ? complaint.customer : m.name} at={m.at}>
            {m.text}
          </Bubble>
        ))}
        {complaint.requested_resolution && (
          <p className="m-0 text-[15px] text-muted">
            <strong className="text-ink">They’d like:</strong> {complaint.requested_resolution}
          </p>
        )}
        {complaint.attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 text-sm">
            {complaint.attachments.map((a) => (
              <span key={a.id} className="inline-flex items-center gap-1.5 rounded-full bg-sand px-3 py-1.5">
                <PaperclipIcon size={16} />
                {a.original_filename}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** Order facts as small tiles (the dates come from the order record, not from what the customer wrote). */
export function FactTiles({ complaint }) {
  const f = complaint.facts || {}
  const tiles = [
    complaint.order_ref && ['Order', complaint.order_ref],
    complaint.product && ['Product', complaint.product],
    f.amount != null && ['Amount', `${Number(f.amount).toFixed(2)} USD${f.amount_source === 'complaint_text' ? ' (their words)' : ''}`],
    f.days_late > 0 && ['Late by', `${f.days_late} working day${f.days_late === 1 ? '' : 's'}`],
    f.days_since_delivery != null && ['Delivered', f.days_since_delivery === 0 ? 'today' : `${f.days_since_delivery} days ago`],
    f.days_since_purchase != null && f.days_since_delivery == null && ['Bought', `${f.days_since_purchase} days ago`],
    complaint.previous_related_count > 0 && ['Earlier complaints', `${complaint.previous_related_count} about this`],
  ].filter(Boolean)
  if (!tiles.length) return <p className="m-0 text-[15px] text-muted">No order linked — ask for the order number if you need it.</p>
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {tiles.map(([label, value]) => (
        <div key={label} className="flex flex-col gap-1 rounded-[14px] bg-sand p-3.5">
          <span className="text-[13px] text-muted">{label}</span>
          <span className="font-semibold">{value}</span>
        </div>
      ))}
    </div>
  )
}
