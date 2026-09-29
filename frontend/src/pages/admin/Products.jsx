import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, EmptyState, ErrorNotice, Loading, SectionTitle, Select, SuccessNotice } from '../../components/ui'
import { useApi } from '../../lib/useApi'
import { codeFrom, fieldLabel, input } from './style'

const KIND = { device: 'Device', service: 'Service' }

function ProductRow({ product, onSaved }) {
  const [name, setName] = useState(product.name)
  const [price, setPrice] = useState(String(product.price))
  const [error, setError] = useState('')
  const changed = name.trim() !== product.name || Number(price) !== product.price

  async function save(change) {
    setError('')
    try {
      await api.patch(`/catalog/products/${product.code}`, change)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <tr className={product.is_active ? '' : 'text-muted'}>
      <td className="border-b border-sand-2 px-2 py-2">
        <input value={name} onChange={(e) => setName(e.target.value)} aria-label={`Name of ${product.name}`} className={`${input} w-full min-w-44`} />
      </td>
      <td className="border-b border-sand-2 px-2 py-2">{KIND[product.kind] || product.kind}</td>
      <td className="border-b border-sand-2 px-2 py-2">
        <input type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} aria-label={`Price of ${product.name} in USD`} className={`${input} w-28`} />
      </td>
      <td className="border-b border-sand-2 px-2 py-2">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={product.is_active} onChange={() => save({ is_active: !product.is_active })} className="size-4 accent-forest" aria-label={`${product.name} on sale`} />
          {!product.is_active && <Badge>Not sold</Badge>}
        </label>
      </td>
      <td className="border-b border-sand-2 px-2 py-2 whitespace-nowrap">
        {changed && (
          <Button variant="light" disabled={name.trim().length < 2 || price === ''} onClick={() => save({ name: name.trim(), price: Number(price) })}>
            Save
          </Button>
        )}
        {error && <span className="text-sm text-rust">{error}</span>}
      </td>
    </tr>
  )
}

function AddProduct({ onAdded }) {
  const [form, setForm] = useState({ name: '', kind: 'device', price: '' })
  const [error, setError] = useState('')
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function add(e) {
    e.preventDefault()
    setError('')
    try {
      const { data } = await api.post('/catalog/products', { code: codeFrom(form.name), name: form.name.trim(), kind: form.kind, price: Number(form.price) })
      setForm({ name: '', kind: 'device', price: '' })
      onAdded(`${data.name} was added. Customers can pick it when they write to us.`)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <Card as="form" onSubmit={add} className="flex flex-col gap-4 p-6">
      <SectionTitle>Add a product</SectionTitle>
      <label className={fieldLabel}>
        Name
        <input required minLength={2} value={form.name} onChange={set('name')} placeholder="e.g. Lumora Smart Doorbell" className={input} />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className={fieldLabel}>
          Kind
          <select value={form.kind} onChange={set('kind')} className={input}>
            {Object.entries(KIND).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={fieldLabel}>
          Price in USD
          <input required type="number" min="0" step="0.01" value={form.price} onChange={set('price')} className={input} />
        </label>
      </div>
      <ErrorNotice message={error} />
      <Button type="submit" className="self-start" disabled={codeFrom(form.name).length < 2 || form.price === ''}>
        Add product
      </Button>
    </Card>
  )
}

export default function Products() {
  const products = useApi('/catalog/products')
  const [kind, setKind] = useState('')
  const [message, setMessage] = useState('')
  const list = (products.data || []).filter((p) => !kind || p.kind === kind).sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <Card className="flex min-w-0 flex-col gap-4 p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-1">
            <SectionTitle>Products</SectionTitle>
            <p className="m-0 text-[15px] text-muted">Price changes apply to new orders only. Products that are not sold any more stay on old orders.</p>
          </div>
          <Select label="Show" value={kind} onChange={setKind} options={[{ value: '', label: 'Everything' }, { value: 'device', label: 'Devices' }, { value: 'service', label: 'Services' }]} />
        </div>
        <ErrorNotice message={products.error} onRetry={products.reload} />
        {products.loading && !products.data && <Loading />}
        {products.data && list.length === 0 && <EmptyState title="No products" />}
        {list.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] border-collapse text-[15px]">
              <thead>
                <tr className="text-left text-[13px] text-muted">
                  {['Name', 'Kind', 'Price (USD)', 'On sale', ''].map((h) => (
                    <th key={h} scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {list.map((p) => (
                  <ProductRow key={`${p.code}-${p.name}-${p.price}-${p.is_active}`} product={p} onSaved={products.reload} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="flex flex-col gap-5">
        <SuccessNotice>{message}</SuccessNotice>
        <AddProduct
          onAdded={(text) => {
            setMessage(text)
            products.reload()
          }}
        />
      </div>
    </div>
  )
}
