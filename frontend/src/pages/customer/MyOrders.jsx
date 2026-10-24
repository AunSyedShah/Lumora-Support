import { useState } from 'react'
import { useLocation } from 'react-router-dom'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorNotice, Loading, SuccessNotice } from '../../components/ui'
import { formatDate, money } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const ORDER_STATUS = { processing: 'Being prepared', shipped: 'On its way', delivered: 'Delivered', cancelled: 'Cancelled' }

function deliveryLine(o) {
  if (o.product_kind === 'service') return o.status === 'cancelled' ? 'Cancelled' : 'Active'
  if (o.status === 'delivered' && o.delivery_date) return `Delivered ${formatDate(o.delivery_date)}`
  if (o.status === 'cancelled') return 'Cancelled'
  if (o.estimated_delivery_date) return `Expected ${formatDate(o.estimated_delivery_date)}`
  return ''
}

export default function MyOrders() {
  const { state } = useLocation()
  const orders = useApi('/orders/my')
  const [cancelling, setCancelling] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  async function cancel() {
    setBusy(true)
    setError('')
    try {
      await api.post(`/orders/${cancelling.order_ref}/cancel`)
      setDone(`${cancelling.order_ref} was cancelled. Because it hadn’t been dispatched, it is refunded in full.`)
      setCancelling(null)
      orders.reload()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  if (orders.loading && !orders.data) return <Loading />
  if (orders.error) return <ErrorNotice message={orders.error} onRetry={orders.reload} />

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="m-0 font-display text-[30px] font-bold tracking-tight">My orders</h1>
        <Button variant="outline" to="/my/shop">
          Shop
        </Button>
      </div>
      {state?.placed && !done && (
        <SuccessNotice>
          <strong>Thanks — your order {state.placed} is placed.</strong> We’ve emailed you a confirmation. Payment is arranged on delivery.
        </SuccessNotice>
      )}
      <SuccessNotice>{done}</SuccessNotice>
      {orders.data.length === 0 && (
        <EmptyState title="No orders yet">
          Orders you place in the Lumora shop show up here.
          <div className="mt-3">
            <Button to="/my/shop">Browse the shop</Button>
          </div>
        </EmptyState>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {orders.data.map((o) => (
          <Card key={o.order_ref} as="article" className="flex flex-col gap-3 p-6">
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-1">
                <span className="text-sm text-muted">{o.order_ref}</span>
                <h2 className="m-0 text-lg font-semibold">
                  {o.product}
                  {o.quantity > 1 && ` × ${o.quantity}`}
                </h2>
              </div>
              <Badge tone={o.status === 'delivered' ? 'sand' : o.status === 'cancelled' ? 'outline' : 'green'}>{ORDER_STATUS[o.status] || o.status}</Badge>
            </div>
            <p className="m-0 text-[15px] text-muted">
              Ordered {formatDate(o.order_date)} · {money(o.total)}
              {o.express && ' · Express'}
            </p>
            <p className="m-0 text-[15px]">{deliveryLine(o)}</p>
            {o.delivery_address && <p className="m-0 text-[14px] whitespace-pre-line text-muted">To: {o.delivery_address}</p>}
            <div className="mt-auto flex flex-wrap gap-2 pt-1">
              <Button variant="light" to="/my/complaints/new" state={{ order: o.order_ref }}>
                Report a problem
              </Button>
              {o.can_cancel && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setError('')
                    setCancelling(o)
                  }}
                >
                  Cancel order
                </Button>
              )}
              <Button variant="ghost" to={`/my/shop/${o.product_code}`}>
                Order again
              </Button>
            </div>
          </Card>
        ))}
      </div>

      <ConfirmDialog
        open={Boolean(cancelling)}
        title="Cancel this order?"
        confirmLabel="Cancel order"
        cancelLabel="Keep my order"
        busyLabel="Cancelling…"
        busy={busy}
        error={error}
        onConfirm={cancel}
        onCancel={() => setCancelling(null)}
      >
        {cancelling && (
          <p className="m-0">
            {cancelling.order_ref} · {cancelling.product}
            {cancelling.quantity > 1 ? ` × ${cancelling.quantity}` : ''}. It hasn’t been dispatched, so you’ll be refunded in full.
          </p>
        )}
      </ConfirmDialog>
    </div>
  )
}
