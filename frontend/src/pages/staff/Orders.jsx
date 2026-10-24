import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, EmptyState, ErrorNotice, Loading, PageTitle, SuccessNotice } from '../../components/ui'
import { formatDate, money } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const PAGE_SIZE = 25
const STATUS = { processing: 'Being prepared', shipped: 'On its way', delivered: 'Delivered', cancelled: 'Cancelled' }
const FILTERS = [
  ['processing', 'To dispatch'],
  ['shipped', 'On their way'],
  ['delivered', 'Delivered'],
  ['cancelled', 'Cancelled'],
  ['', 'All'],
]
const NEXT = { processing: ['shipped', 'Mark as shipped'], shipped: ['delivered', 'Mark as delivered'] }

/** Managers and administrators move shop orders along: being prepared → on its way → delivered. */
export default function Orders() {
  const [status, setStatus] = useState('processing')
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState('')
  const list = useApi('/orders', { params: { status: status || undefined, page, page_size: PAGE_SIZE } })
  const items = list.data?.items || []
  const pages = Math.max(1, Math.ceil((list.data?.count || 0) / PAGE_SIZE))

  async function advance(order, next) {
    setBusy(order.order_ref)
    setError('')
    setDone('')
    try {
      await api.patch(`/orders/${order.order_ref}/status`, { status: next })
      setDone(`${order.order_ref} is now ${STATUS[next].toLowerCase()}.`)
      list.reload()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <PageTitle eyebrow="Customers are emailed when an order ships" title="Orders" />
      <div className="flex flex-wrap gap-2" role="group" aria-label="Show orders">
        {FILTERS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={status === value}
            onClick={() => {
              setStatus(value)
              setPage(1)
            }}
            className={`cursor-pointer rounded-full px-4 py-2 text-[15px] ${status === value ? 'border border-forest bg-forest font-semibold text-white' : 'border border-line bg-white text-ink hover:bg-sand'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <ErrorNotice message={error || list.error} onRetry={list.error ? list.reload : undefined} />
      <SuccessNotice>{done}</SuccessNotice>
      {list.loading && !list.data && <Loading />}
      {list.data && items.length === 0 && <EmptyState title="Nothing here">No orders match this filter.</EmptyState>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((o) => {
          const next = NEXT[o.status]
          return (
            <Card key={o.order_ref} as="article" className="flex flex-col gap-2.5 p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-col">
                  <span className="text-sm text-muted">
                    {o.order_ref} · {o.customer}
                  </span>
                  <h2 className="m-0 text-[17px] font-semibold">
                    {o.product}
                    {o.quantity > 1 && ` × ${o.quantity}`}
                  </h2>
                </div>
                <Badge tone={o.status === 'delivered' ? 'sand' : o.status === 'cancelled' ? 'outline' : 'green'}>{STATUS[o.status] || o.status}</Badge>
              </div>
              <p className="m-0 text-[15px] text-muted">
                Ordered {formatDate(o.order_date)} · {money(o.total)}
                {o.express && ' · Express'}
                {o.estimated_delivery_date && o.product_kind === 'device' && ` · due ${formatDate(o.estimated_delivery_date)}`}
              </p>
              {o.delivery_address && <p className="m-0 text-[14px] whitespace-pre-line">{o.delivery_address}</p>}
              {next && (
                <Button className="mt-1 self-start" disabled={busy === o.order_ref} onClick={() => advance(o, next[0])}>
                  {busy === o.order_ref ? 'Saving…' : next[1]}
                </Button>
              )}
            </Card>
          )
        })}
      </div>
      {pages > 1 && (
        <nav aria-label="Pages" className="flex items-center gap-3">
          <Button variant="light" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span className="text-[15px] text-muted">
            Page {page} of {pages}
          </span>
          <Button variant="light" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </nav>
      )}
    </div>
  )
}
