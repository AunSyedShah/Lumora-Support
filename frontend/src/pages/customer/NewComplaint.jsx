import { Form, Formik, useFormikContext } from 'formik'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../../api/client'
import { useAuth } from '../../auth/context'
import { Button, Card, ErrorNotice, FocusFirstError, PillChoice, SectionTitle, SelectField, TextArea, TextField } from '../../components/ui'
import { ALLOWED_FILES, checkFiles, MAX_FILES } from '../../lib/files'
import { formatDate } from '../../lib/format'
import { useApi } from '../../lib/useApi'

// The same limits the API applies, checked here so people see them before sending.
const LIMITS = { title: 200, description: 5000, requested_resolution: 500 }

function validate(v, needsPhone) {
  const errors = {}
  if (needsPhone && v.preferred_contact === 'phone' && v.phone.replace(/\D/g, '').length < 7) errors.phone = 'Add the number we should call.'
  if (v.title.trim().length < 5) errors.title = 'Give your complaint a short title (at least 5 characters).'
  else if (v.title.trim().length > LIMITS.title) errors.title = `Please keep the title under ${LIMITS.title} characters.`
  const words = v.description.trim().split(/\s+/).filter(Boolean)
  if (v.description.trim().length < 20 || words.length < 4) errors.description = 'Please describe what happened in a sentence or two.'
  else if (v.description.trim().length > LIMITS.description) errors.description = `Please shorten this to ${LIMITS.description} characters — you can add more in a reply.`
  return errors
}

/** Picking an order fills in its product (the customer can still change it). */
function ProductFromOrder({ orders, products }) {
  const { values, setFieldValue } = useFormikContext()
  const lastOrder = useRef(null)
  useEffect(() => {
    if (values.order_ref === lastOrder.current) return // only when the order itself changes
    const order = orders.find((o) => o.order_ref === values.order_ref)
    const product = order && products.find((p) => p.name === order.product)
    if (!product) return // wait until both lists have loaded
    lastOrder.current = values.order_ref
    setFieldValue('product', product.code)
  }, [values.order_ref, orders, products, setFieldValue])
  return null
}

export default function NewComplaint() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useAuth()
  const needsPhone = !user.phone
  const orders = useApi('/orders/my')
  const products = useApi('/catalog/products', { params: { active_only: true } })
  const earlier = useApi('/complaints/my')
  const fileInput = useRef(null)
  const [files, setFiles] = useState([])
  const [fileError, setFileError] = useState('')
  const [error, setError] = useState('')
  const [duplicateOf, setDuplicateOf] = useState(null)

  const orderOptions = [
    { value: '', label: 'Not about an order' },
    ...(orders.data || []).map((o) => ({ value: o.order_ref, label: `${o.order_ref} · ${o.product}${o.quantity > 1 ? ` × ${o.quantity}` : ''} · ${formatDate(o.order_date)}` })),
  ]
  const productOptions = [{ value: '', label: 'Not sure / not listed' }, ...(products.data || []).map((p) => ({ value: p.code, label: p.name }))]
  const earlierOptions = [
    { value: '', label: 'No, this is new' },
    ...(earlier.data || []).map((c) => ({ value: c.complaint_id, label: `${c.complaint_id} · ${c.title}` })),
  ]

  function pickFiles(event) {
    const picked = Array.from(event.target.files || [])
    const problem = checkFiles(picked)
    setFileError(problem)
    setFiles(problem ? [] : picked)
    if (problem && fileInput.current) fileInput.current.value = ''
  }

  async function submit(values) {
    setError('')
    setDuplicateOf(null)
    try {
      const { data } = await api.post('/complaints', {
        title: values.title.trim(),
        description: values.description.trim(),
        order_ref: values.order_ref || null,
        product: values.product || null,
        previous_complaint_ref: values.previous_complaint_ref || null,
        requested_resolution: values.requested_resolution.trim(),
        supporting_information: needsPhone && values.preferred_contact === 'phone' ? `Phone: ${values.phone.trim()}` : '',
        preferred_contact: values.preferred_contact,
        channel: 'web',
      })
      const notes = [...data.warnings]
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        try {
          await api.post(`/complaints/${data.complaint_id}/attachments`, form)
        } catch (e) {
          notes.push(`${file.name} could not be attached: ${errorMessage(e)}`)
        }
      }
      navigate(`/my/complaints/${data.complaint_id}`, { state: { justSent: true, notes } })
    } catch (e) {
      if (e.response?.status === 409 && e.response.data?.existing_complaint) setDuplicateOf(e.response.data.existing_complaint)
      setError(errorMessage(e))
    }
  }

  return (
    <div className="grid grid-cols-1 gap-7 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card className="px-6 py-8 md:px-10">
        <Formik
          initialValues={{ title: '', description: '', order_ref: location.state?.order || '', product: '', requested_resolution: '', previous_complaint_ref: '', preferred_contact: 'email', phone: '' }}
          validate={(values) => validate(values, needsPhone)}
          onSubmit={submit}
          enableReinitialize={false}
        >
          {({ isSubmitting, values }) => (
            <Form className="flex flex-col gap-6" noValidate>
              <FocusFirstError />
              <ProductFromOrder orders={orders.data || []} products={products.data || []} />
              <h1 className="m-0 font-display text-[34px] font-bold tracking-tight">Tell us what happened</h1>
              <ErrorNotice message={error} />
              {duplicateOf && (
                <p className="m-0">
                  <Link to={`/my/complaints/${duplicateOf}`} className="font-semibold text-forest">
                    Open {duplicateOf}
                  </Link>
                </p>
              )}
              <TextField name="title" label="In a few words, what’s wrong?" placeholder="e.g. Thermostat order hasn’t arrived" maxLength={LIMITS.title} />
              <TextArea name="description" label="Tell us more" rows={5} placeholder="What happened, when, and what you have already tried." maxLength={LIMITS.description} />
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                {/* only asked when there is something to choose */}
                {orders.data?.length > 0 && <SelectField name="order_ref" label="Which order?" hint="(if it’s about one)" options={orderOptions} />}
                <SelectField name="product" label="Which product?" options={productOptions} />
                {earlier.data?.length > 0 && <SelectField name="previous_complaint_ref" label="Already told us about this?" hint="(optional)" options={earlierOptions} />}
                <div className="md:col-span-2">
                  <TextField name="requested_resolution" label="What would you like us to do?" placeholder="e.g. Tell me when it will arrive" maxLength={LIMITS.requested_resolution} />
                </div>
              </div>
              <PillChoice
                name="preferred_contact"
                legend="How should we get back to you?"
                options={[
                  { value: 'email', label: 'Email' },
                  { value: 'phone', label: 'Phone' },
                ]}
              />
              {needsPhone && values.preferred_contact === 'phone' && <TextField name="phone" type="tel" label="Your phone number" placeholder="e.g. +1 555 0100" autoComplete="tel" />}
              <div className="flex flex-col gap-2">
                <label htmlFor="files" className="text-[15px] font-semibold">
                  Photos or documents <span className="font-normal text-muted">(optional — PDF, PNG, JPG, up to {MAX_FILES} files)</span>
                </label>
                <div className="rounded-[14px] border-[1.5px] border-dashed border-line bg-cream/40 p-4">
                  <input id="files" ref={fileInput} type="file" multiple accept={ALLOWED_FILES.join(',')} onChange={pickFiles} className="text-[15px]" />
                </div>
                {fileError && <p className="m-0 text-sm font-semibold text-rust">{fileError}</p>}
              </div>
              <div className="flex flex-wrap items-center gap-4">
                <Button type="submit" disabled={isSubmitting} className="min-h-12 text-base">
                  {isSubmitting ? 'Sending…' : 'Send complaint'}
                </Button>
                <span className="text-sm text-muted">
                  {isSubmitting ? 'We’re reading it and checking it against our policies — this can take up to half a minute.' : 'Please don’t include card numbers or passwords.'}
                </span>
              </div>
            </Form>
          )}
        </Formik>
      </Card>

      <aside aria-label="What happens next" className="flex flex-col gap-5">
        <div className="flex flex-col gap-4 rounded-[26px] bg-sun p-7 text-[#2e2200]">
          <SectionTitle>What happens next</SectionTitle>
          <ol className="m-0 flex flex-col gap-3 pl-5 text-base leading-snug">
            <li>We read your complaint straight away.</li>
            <li>The right team picks it up — urgent safety or security problems go to the front of the line.</li>
            <li>
              You can follow every step and reply in{' '}
              <Link to="/my/complaints" className="font-semibold text-[#2e2200]">
                My complaints
              </Link>
              .
            </li>
            <li>If you choose email, we send you every reply too — and you can answer straight from your inbox.</li>
          </ol>
        </div>
        <Card className="flex flex-col gap-2 p-6">
          <h2 className="m-0 font-display text-lg font-bold">Is it smoking, sparking or very hot?</h2>
          <p className="m-0 text-[15px] leading-relaxed text-muted">Unplug the device and keep away from it, then tell us here. Safety reports are handled first.</p>
        </Card>
      </aside>
    </div>
  )
}
