import { Form, Formik } from 'formik'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, errorMessage } from '../../api/client'
import { Button, Card, ConfirmDialog, ErrorNotice, FocusFirstError, Loading, PillChoice, SectionTitle, SelectField, TextArea } from '../../components/ui'
import { money } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const ADDRESS_MIN = 10

function validate(values, isDevice) {
  const errors = {}
  if (isDevice && values.delivery_address.trim().length < ADDRESS_MIN) errors.delivery_address = 'Enter the full delivery address: street, area and city.'
  return errors
}

/** Order one product. The server sets the price and the delivery date; this page only shows them. */
export default function Checkout() {
  const { code } = useParams()
  const navigate = useNavigate()
  const catalog = useApi('/orders/catalog')
  const earlier = useApi('/orders/my')
  const [pending, setPending] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if ((catalog.loading && !catalog.data) || (earlier.loading && !earlier.data)) return <Loading />
  if (catalog.error) return <ErrorNotice message={catalog.error} onRetry={catalog.reload} />
  const product = catalog.data.products.find((p) => p.code === code)
  if (!product) {
    return (
      <Card className="flex flex-col items-start gap-3 p-8">
        <h1 className="m-0 font-display text-[26px] font-bold">That product isn’t for sale any more</h1>
        <Button to="/my/shop">Back to the shop</Button>
      </Card>
    )
  }
  const { express_fee: expressFee, max_quantity: maxQuantity, standard_days: standardDays, express_days: expressDays } = catalog.data
  const isDevice = product.kind === 'device'
  const lastAddress = (earlier.data || []).find((o) => o.delivery_address)?.delivery_address || ''
  const quantityOptions = Array.from({ length: maxQuantity }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))
  const totalFor = (v) => product.price * Number(v.quantity) + (isDevice && v.delivery === 'express' ? expressFee : 0)

  async function place() {
    setBusy(true)
    setError('')
    try {
      const { data } = await api.post('/orders', {
        product: product.code,
        quantity: Number(pending.quantity),
        express: isDevice && pending.delivery === 'express',
        delivery_address: isDevice ? pending.delivery_address.trim() : '',
      })
      navigate('/my/orders', { state: { placed: data.order_ref } })
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-7 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card className="px-6 py-8 md:px-10">
        <Formik initialValues={{ quantity: '1', delivery: 'standard', delivery_address: lastAddress }} validate={(v) => validate(v, isDevice)} onSubmit={(values) => setPending(values)}>
          {({ values }) => (
            <Form className="flex flex-col gap-6" noValidate>
              <FocusFirstError />
              <div className="flex flex-col gap-1">
                <Link to="/my/shop" className="text-[15px] font-semibold text-forest">
                  ← Shop
                </Link>
                <h1 className="m-0 font-display text-[32px] font-bold tracking-tight">{product.name}</h1>
                <p className="m-0 text-[15px] text-muted">{money(product.price)}{isDevice ? ' each' : ''}</p>
              </div>
              {isDevice && <SelectField name="quantity" label="How many?" options={quantityOptions} />}
              {isDevice && (
                <PillChoice
                  name="delivery"
                  legend="Delivery"
                  options={[
                    { value: 'standard', label: `Standard · free · up to ${standardDays} business days` },
                    { value: 'express', label: `Express · ${money(expressFee)} · up to ${expressDays} business days` },
                  ]}
                />
              )}
              {isDevice && <TextArea name="delivery_address" label="Delivery address" rows={3} placeholder="Street, area, city and postcode" autoComplete="street-address" maxLength={500} />}
              {!isDevice && <p className="m-0 text-[15px] text-muted">Nothing is delivered: your subscription is active as soon as you order.</p>}
              <div className="flex flex-wrap items-center gap-4">
                <Button type="submit" className="min-h-12 text-base">
                  Review order · {money(totalFor(values))}
                </Button>
                <span className="text-sm text-muted">Payment is arranged on delivery. Nothing is charged now.</span>
              </div>
            </Form>
          )}
        </Formik>
      </Card>

      <aside aria-label="About ordering" className="flex flex-col gap-5">
        <div className="flex flex-col gap-3 rounded-[26px] bg-sun p-7 text-[#2e2200]">
          <SectionTitle>Good to know</SectionTitle>
          <ul className="m-0 flex flex-col gap-2.5 pl-5 text-base leading-snug">
            <li>You can cancel for a full refund until your order is dispatched.</li>
            <li>We email you when it’s confirmed and when it’s on its way.</li>
            <li>If anything goes wrong, you can tell us from “My orders”.</li>
          </ul>
        </div>
      </aside>

      <ConfirmDialog
        open={Boolean(pending)}
        title="Place this order?"
        confirmLabel="Place order"
        cancelLabel="Go back"
        busyLabel="Placing…"
        variant="primary"
        busy={busy}
        error={error}
        onConfirm={place}
        onCancel={() => {
          setPending(null)
          setError('')
        }}
      >
        {pending && (
          <>
            <p className="m-0 text-ink">
              <strong>
                {isDevice ? `${pending.quantity} × ` : ''}
                {product.name}
              </strong>{' '}
              · {money(totalFor(pending))}
              {isDevice && pending.delivery === 'express' ? ` (includes ${money(expressFee)} express delivery)` : ''}
            </p>
            {isDevice && <p className="m-0 whitespace-pre-line">Delivering to: {pending.delivery_address.trim()}</p>}
            <p className="m-0">Payment is arranged on delivery.</p>
          </>
        )}
      </ConfirmDialog>
    </div>
  )
}
