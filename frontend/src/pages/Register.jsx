import { Form, Formik } from 'formik'
import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { errorMessage } from '../api/client'
import { homeFor, useAuth } from '../auth/context'
import { Button, ErrorNotice, PillChoice, TextField } from '../components/ui'
import { AuthPanel } from './Login'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validate(v) {
  const errors = {}
  if (v.username.trim().length < 3) errors.username = 'Choose a username of at least 3 characters.'
  if (!EMAIL.test(v.email.trim())) errors.email = 'Enter a valid email address.'
  if (v.password.length < 8) errors.password = 'Use at least 8 characters.'
  if (v.confirm !== v.password) errors.confirm = 'The passwords don’t match.'
  return errors
}

export default function Register() {
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')

  if (user) return <Navigate to={homeFor(user.role)} replace />

  async function submit(values) {
    setError('')
    try {
      const fields = { ...values }
      delete fields.confirm // only checked here, not sent
      const me = await register({ ...fields, username: fields.username.trim(), email: fields.email.trim() })
      navigate(homeFor(me.role), { replace: true })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="grid min-h-screen grid-cols-1 gap-6 bg-cream p-6 md:grid-cols-2">
      <AuthPanel />
      <main className="flex items-center justify-center py-6">
        <Formik
          initialValues={{ username: '', email: '', first_name: '', last_name: '', phone: '', customer_type: 'standard', password: '', confirm: '' }}
          validate={validate}
          onSubmit={submit}
        >
          {({ isSubmitting }) => (
            <Form className="flex w-full max-w-[460px] flex-col gap-5" noValidate>
              <h2 className="m-0 font-display text-[32px] font-bold tracking-tight">Create your account</h2>
              <ErrorNotice message={error} />
              <div className="grid grid-cols-2 gap-4">
                <TextField name="first_name" label="First name" autoComplete="given-name" />
                <TextField name="last_name" label="Last name" autoComplete="family-name" />
              </div>
              <TextField name="email" label="Email" type="email" autoComplete="email" />
              <TextField name="phone" label="Phone" hint="(optional)" type="tel" autoComplete="tel" />
              <TextField name="username" label="Username" autoComplete="username" />
              <PillChoice
                name="customer_type"
                legend="Account type"
                options={[
                  { value: 'standard', label: 'Home' },
                  { value: 'premium', label: 'LumoraCare+ member' },
                  { value: 'business', label: 'Business' },
                ]}
              />
              <div className="grid grid-cols-2 gap-4">
                <TextField name="password" label="Password" type="password" autoComplete="new-password" />
                <TextField name="confirm" label="Repeat password" type="password" autoComplete="new-password" />
              </div>
              <Button type="submit" disabled={isSubmitting} className="min-h-12 text-base">
                {isSubmitting ? 'Creating your account…' : 'Create account'}
              </Button>
              <p className="m-0 text-center text-[15px] text-muted">
                Already have an account?{' '}
                <Link to="/login" className="font-semibold text-forest">
                  Sign in
                </Link>
              </p>
            </Form>
          )}
        </Formik>
      </main>
    </div>
  )
}
