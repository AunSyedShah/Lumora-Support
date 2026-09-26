import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, EmptyState, ErrorNotice, Loading, SectionTitle, Select, SuccessNotice } from '../../components/ui'
import { formatDate } from '../../lib/format'
import { CUSTOMER_TYPE, ROLE } from '../../lib/labels'
import { useApi } from '../../lib/useApi'
import { fieldLabel, input } from './style'

const STAFF_ROLES = ['agent', 'reviewer', 'manager', 'admin']
const EMPTY = { first_name: '', last_name: '', username: '', email: '', password: '', role: 'agent' }

function AddPerson({ onAdded }) {
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function add(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { data } = await api.post('/auth/users', form)
      setForm(EMPTY)
      onAdded(`${data.first_name || data.username} can now sign in as ${ROLE[data.role].toLowerCase()}.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="form" onSubmit={add} className="flex flex-col gap-4 p-6">
      <SectionTitle>Add a team member</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        <label className={fieldLabel}>
          First name
          <input value={form.first_name} onChange={set('first_name')} className={input} />
        </label>
        <label className={fieldLabel}>
          Last name
          <input value={form.last_name} onChange={set('last_name')} className={input} />
        </label>
        <label className={fieldLabel}>
          Username
          <input required minLength={3} value={form.username} onChange={set('username')} autoComplete="off" className={input} />
        </label>
        <label className={fieldLabel}>
          Email
          <input required type="email" value={form.email} onChange={set('email')} className={input} />
        </label>
        <label className={fieldLabel}>
          First password
          <input required type="password" minLength={8} value={form.password} onChange={set('password')} autoComplete="new-password" className={input} />
        </label>
        <label className={fieldLabel}>
          Job
          <select value={form.role} onChange={set('role')} className={input}>
            {STAFF_ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE[r]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="m-0 text-[14px] text-muted">At least 8 characters, not too common. Share it with them privately.</p>
      <ErrorNotice message={error} />
      <Button type="submit" className="self-start" disabled={busy}>
        {busy ? 'Adding…' : 'Add'}
      </Button>
    </Card>
  )
}

export default function People() {
  const [role, setRole] = useState('staff')
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('')
  const users = useApi('/auth/users', { params: role && role !== 'staff' ? { role } : {} })

  const words = search.trim().toLowerCase()
  const list = (users.data || [])
    .filter((u) => role !== 'staff' || u.role !== 'customer')
    .filter((u) => !words || `${u.first_name} ${u.last_name} ${u.username} ${u.email}`.toLowerCase().includes(words))

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <Card className="flex min-w-0 flex-col gap-4 p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <SectionTitle>People</SectionTitle>
          <div className="flex flex-wrap gap-2">
            <label className={fieldLabel}>
              Find
              <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or email" className={input} />
            </label>
            <Select label="Show" value={role} onChange={setRole} options={[{ value: 'staff', label: 'Team members' }, { value: '', label: 'Everyone' }, ...Object.entries(ROLE).map(([value, label]) => ({ value, label }))]} />
          </div>
        </div>
        <ErrorNotice message={users.error} onRetry={users.reload} />
        {users.loading && !users.data && <Loading />}
        {users.data && list.length === 0 && <EmptyState title="Nobody found" />}
        {list.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] border-collapse text-[15px]">
              <thead>
                <tr className="text-left text-[13px] text-muted">
                  {['Name', 'Email', 'Job', 'Joined'].map((h) => (
                    <th key={h} scope="col" className="border-b border-line-soft px-2 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {list.map((u) => (
                  <tr key={u.id}>
                    <td className="border-b border-sand-2 px-2 py-2.5">
                      <div className="font-semibold">{`${u.first_name} ${u.last_name}`.trim() || u.username}</div>
                      <div className="text-[13px] text-muted">{u.username}</div>
                    </td>
                    <td className="border-b border-sand-2 px-2 py-2.5">{u.email}</td>
                    <td className="border-b border-sand-2 px-2 py-2.5">
                      <Badge tone={u.role === 'customer' ? 'sand' : 'green'}>{u.role === 'customer' ? CUSTOMER_TYPE[u.customer_type] : ROLE[u.role]}</Badge>
                    </td>
                    <td className="border-b border-sand-2 px-2 py-2.5 whitespace-nowrap">{formatDate(u.date_joined)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="flex flex-col gap-5">
        <SuccessNotice>{message}</SuccessNotice>
        <AddPerson
          onAdded={(text) => {
            setMessage(text)
            users.reload()
          }}
        />
      </div>
    </div>
  )
}
