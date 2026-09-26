import { Badge, Button, Card, EmptyState, ErrorNotice, Loading } from '../../components/ui'
import { formatDate, money } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const ORDER_STATUS = { processing: 'Being prepared', shipped: 'On its way', delivered: 'Delivered', cancelled: 'Cancelled' }

function deliveryLine(o) {
  if (o.status === 'delivered' && o.delivery_date) return `Delivered ${formatDate(o.delivery_date)}`
  if (o.status === 'cancelled') return 'Cancelled'
  if (o.estimated_delivery_date) return `Expected ${formatDate(o.estimated_delivery_date)}`
  return ''
}

export default function MyOrders() {
  const orders = useApi('/orders/my')
  if (orders.loading && !orders.data) return <Loading />
  if (orders.error) return <ErrorNotice message={orders.error} onRetry={orders.reload} />

  return (
    <div className="flex flex-col gap-5">
      <h1 className="m-0 font-display text-[30px] font-bold tracking-tight">My orders</h1>
      {orders.data.length === 0 && <EmptyState title="No orders yet">Orders you place in the Lumora store show up here.</EmptyState>}
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
              Ordered {formatDate(o.order_date)} · {money(o.amount)}
              {o.express && ' · Express'}
            </p>
            <p className="m-0 text-[15px]">{deliveryLine(o)}</p>
            <Button variant="light" to="/my/complaints/new" state={{ order: o.order_ref }} className="self-start">
              Report a problem
            </Button>
          </Card>
        ))}
      </div>
    </div>
  )
}
