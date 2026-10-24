import { Badge, Button, Card, ErrorNotice, Loading } from '../../components/ui'
import { money } from '../../lib/format'
import { useApi } from '../../lib/useApi'

/** What a customer can order. Prices come from the server; ordering happens on the next page. */
export default function Shop() {
  const catalog = useApi('/orders/catalog')
  if (catalog.loading && !catalog.data) return <Loading />
  if (catalog.error) return <ErrorNotice message={catalog.error} onRetry={catalog.reload} />
  const { products, express_fee: expressFee, standard_days: standard, express_days: express } = catalog.data

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <h1 className="m-0 font-display text-[30px] font-bold tracking-tight">Shop</h1>
        <p className="m-0 max-w-2xl text-[15px] text-muted">
          Standard delivery is free and takes up to {standard} business days. Express delivery takes up to {express} for {money(expressFee)}. Payment is arranged on delivery — there is nothing to pay now.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {products.map((p) => (
          <Card key={p.code} as="article" className="flex flex-col gap-3 p-6">
            <div className="flex items-start justify-between gap-3">
              <h2 className="m-0 text-lg font-semibold">{p.name}</h2>
              <Badge tone={p.kind === 'service' ? 'soft' : 'sand'}>{p.kind === 'service' ? 'Subscription' : 'Device'}</Badge>
            </div>
            <p className="m-0 font-display text-[26px] font-bold">
              {money(p.price)}
            </p>
            <Button to={`/my/shop/${p.code}`} className="mt-auto self-start">
              {p.kind === 'service' ? 'Subscribe' : 'Order'}
            </Button>
          </Card>
        ))}
        {products.length === 0 && <Card className="p-6 text-muted">Nothing is for sale right now.</Card>}
      </div>
    </div>
  )
}
