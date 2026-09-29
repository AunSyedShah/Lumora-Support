import { Form, Formik } from 'formik'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, errorMessage } from '../../api/client'
import { Button, Card, ErrorNotice, FocusFirstError, PageTitle, PillChoice, SectionTitle, SelectField, SuccessNotice, TextArea, TextField } from '../../components/ui'
import { ALLOWED_FILES, checkFiles, MAX_FILES } from '../../lib/files'
import { formatDate } from '../../lib/format'
import { useApi } from '../../lib/useApi'
import { fieldLabel, input } from '../admin/style'

const EMPTY = { title: '', description: '', channel: 'email', order_ref: '', product: '', requested_resolution: '', previous_complaint_ref: '', supporting_information: '', preferred_contact: 'email' }

function validate(v) {
  const errors = {}
  if (v.title.trim().length < 5) errors.title = 'Give it a short title (at least 5 characters).'
  const words = v.description.trim().split(/\s+/).filter(Boolean)
  if (v.description.trim().length < 20 || words.length < 4) errors.description = 'Write down what the customer told us in a sentence or two.'
  return errors
}

/** Staff log a complaint that reached us another way (email, chat, a letter...) for a customer. */
export default function LogComplaint() {
  const [username, setUsername] = useState('')
  const [customer, setCustomer] = useState('')
  const orders = useApi(customer ? '/orders' : null, { params: { customer, page_size: 50 } })
  const products = useApi('/catalog/products', { params: { active_only: true } })
  const fileInput = useRef(null)
  const [files, setFiles] = useState([])
  const [fileError, setFileError] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(null)

  const orderList = orders.data?.items || []
  const productOptions = [{ value: '', label: 'Not sure / not listed' }, ...(products.data || []).map((p) => ({ value: p.code, label: p.name }))]
  const orderOptions = [
    { value: '', label: 'Not about an order' },
    ...orderList.map((o) => ({ value: o.order_ref, label: `${o.order_ref} · ${o.product}${o.quantity > 1 ? ` × ${o.quantity}` : ''} · ${formatDate(o.order_date)}` })),
  ]

  function pickFiles(event) {
    const picked = Array.from(event.target.files || [])
    const problem = checkFiles(picked)
    setFileError(problem)
    setFiles(problem ? [] : picked)
    if (problem && fileInput.current) fileInput.current.value = ''
  }

  async function submit(values, { resetForm }) {
    setError('')
    setDone(null)
    const who = username.trim()
    if (!who) {
      setError('Who is the complaint from? Enter their username first.')
      return
    }
    try {
      const { data } = await api.post('/complaints', {
        ...values,
        title: values.title.trim(),
        description: values.description.trim(),
        order_ref: values.order_ref.trim() || null,
        product: values.product || null,
        previous_complaint_ref: values.previous_complaint_ref.trim() || null,
        requested_resolution: values.requested_resolution.trim(),
        supporting_information: values.supporting_information.trim(),
        customer_username: who,
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
      setDone({ id: data.complaint_id, notes, related: data.related_complaint })
      setFiles([])
      if (fileInput.current) fileInput.current.value = ''
      resetForm()
    } catch (e) {
      const status = e.response?.status
      if (status === 404 && /user/i.test(e.response.data?.detail || '')) setError(`We couldn’t find a customer with the username “${who}”.`)
      else if (status === 409 && e.response.data?.existing_complaint) setDone({ id: e.response.data.existing_complaint, duplicate: true, notes: [] })
      else setError(errorMessage(e))
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <PageTitle eyebrow="For complaints that reached us by email, chat or letter" title="Log a complaint" />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="flex flex-col gap-6 px-6 py-7 md:px-8">
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              setCustomer(username.trim())
            }}
          >
            <label className={`${fieldLabel} min-w-0 flex-1 basis-56`}>
              Customer’s username
              <input required value={username} onChange={(e) => setUsername(e.target.value)} placeholder="e.g. cust012" className={input} />
            </label>
            <Button type="submit" variant="light">
              Show their orders
            </Button>
          </form>
          {customer && orders.data && (
            <p className="m-0 -mt-3 text-[14px] text-muted">
              {orderList.length ? `${orderList.length} order${orderList.length === 1 ? '' : 's'} found for ${customer}.` : `No orders you can see for ${customer} — type the order number below if they gave one.`}
            </p>
          )}
          <ErrorNotice message={orders.error} />

          <Formik initialValues={EMPTY} validate={validate} onSubmit={submit}>
            {({ isSubmitting }) => (
              <Form className="flex flex-col gap-6" noValidate>
                <FocusFirstError />
                <ErrorNotice message={error} />
                <PillChoice
                  name="channel"
                  legend="How did it reach us?"
                  options={[
                    { value: 'email', label: 'Email' },
                    { value: 'chat', label: 'Chat' },
                    { value: 'web', label: 'Website form' },
                    { value: 'upload', label: 'Letter or file' },
                  ]}
                />
                <TextField name="title" label="In a few words, what’s wrong?" placeholder="e.g. Doorbell stopped recording" />
                <TextArea name="description" label="What the customer told us" hint="(their words, as far as possible)" rows={6} />
                <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                  {orderList.length ? (
                    <SelectField name="order_ref" label="Which order?" options={orderOptions} />
                  ) : (
                    <TextField name="order_ref" label="Order number" hint="(if they gave one)" placeholder="e.g. ORD-10042" />
                  )}
                  <SelectField name="product" label="Which product?" options={productOptions} />
                  <TextField name="requested_resolution" label="What do they want us to do?" placeholder="e.g. A replacement" />
                  <TextField name="previous_complaint_ref" label="Earlier complaint number" hint="(if they mentioned one)" placeholder="e.g. CMP-00012" />
                </div>
                <TextArea name="supporting_information" label="Anything else we know" hint="(optional)" rows={3} />
                <PillChoice
                  name="preferred_contact"
                  legend="How should we get back to them?"
                  options={[
                    { value: 'email', label: 'Email' },
                    { value: 'phone', label: 'Phone' },
                    { value: 'chat', label: 'Chat' },
                  ]}
                />
                <div className="flex flex-col gap-2">
                  <label htmlFor="staff-files" className="text-[15px] font-semibold">
                    Photos or documents they sent <span className="font-normal text-muted">(optional, up to {MAX_FILES} files)</span>
                  </label>
                  <input id="staff-files" ref={fileInput} type="file" multiple accept={ALLOWED_FILES.join(',')} onChange={pickFiles} className="text-[15px]" />
                  {fileError && <p className="m-0 text-sm font-semibold text-rust">{fileError}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <Button type="submit" disabled={isSubmitting} className="min-h-12 text-base">
                    {isSubmitting ? 'Saving…' : 'Log complaint'}
                  </Button>
                  {isSubmitting && <span className="text-sm text-muted">It is being read and sent to the right team — this takes a few seconds.</span>}
                </div>
              </Form>
            )}
          </Formik>
        </Card>

        <aside className="flex flex-col gap-5">
          {done && (
            <SuccessNotice>
              <p className="m-0 font-semibold">{done.duplicate ? `This is the same as ${done.id}, which is already open.` : `${done.id} was logged and sent to the right team.`}</p>
              {done.related && <p className="m-0 mt-1">It looks related to {done.related}.</p>}
              {done.notes.map((n) => (
                <p key={n} className="m-0 mt-1 text-[14px]">
                  {n}
                </p>
              ))}
              <Link to={`/complaints/${done.id}`} className="mt-2 inline-block font-semibold text-forest">
                Open {done.id}
              </Link>
            </SuccessNotice>
          )}
          <Card className="flex flex-col gap-2 p-6">
            <SectionTitle>Good to know</SectionTitle>
            <ul className="m-0 flex flex-col gap-2 pl-5 text-[15px] leading-relaxed text-muted">
              <li>The customer sees this complaint in their account, just as if they had sent it themselves.</li>
              <li>Leave out card numbers and passwords — they are hidden automatically, but it is better not to copy them.</li>
              <li>Safety and account-security problems go to the front of the line.</li>
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  )
}
