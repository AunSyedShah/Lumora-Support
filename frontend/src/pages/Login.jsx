import { Form, Formik } from 'formik'
import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { errorMessage } from '../api/client'
import { homeFor, useAuth } from '../auth/context'
import Logo from '../components/Logo'
import { Button, ErrorNotice, TextField } from '../components/ui'

export function AuthPanel() {
  return (
    <section className="hidden flex-col justify-between rounded-[28px] bg-forest p-12 text-cream md:flex">
      <div className="flex items-center gap-3">
        <Logo onDark />
        <span className="font-display text-[22px] font-bold">Lumora Support</span>
      </div>
      <div className="flex max-w-[460px] flex-col gap-4">
        <h1 className="m-0 font-display text-[52px] leading-[1.05] font-bold tracking-tight">Something not right at home? Tell us.</h1>
        <p className="m-0 text-lg leading-relaxed text-[#d7e6dc]">
          Report a problem with a Lumora device, an order or your subscription, and follow every step until it’s sorted.
        </p>
      </div>
      <p className="m-0 text-sm text-sage">Staff sign in here too.</p>
    </section>
  )
}

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [error, setError] = useState('')

  if (user) return <Navigate to={homeFor(user.role)} replace />

  async function submit(values) {
    setError('')
    try {
      const me = await login(values.username.trim(), values.password)
      navigate(location.state?.from || homeFor(me.role), { replace: true })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="grid min-h-screen grid-cols-1 gap-6 bg-cream p-6 md:grid-cols-2">
      <AuthPanel />
      <main className="flex items-center justify-center">
        <Formik
          initialValues={{ username: '', password: '' }}
          validate={(v) => ({
            ...(!v.username.trim() && { username: 'Enter your email or username.' }),
            ...(!v.password && { password: 'Enter your password.' }),
          })}
          onSubmit={submit}
        >
          {({ isSubmitting }) => (
            <Form className="flex w-full max-w-[400px] flex-col gap-5" noValidate>
              <div className="flex items-center gap-3 md:hidden">
                <Logo />
                <span className="font-display text-xl font-bold">Lumora Support</span>
              </div>
              <h2 className="m-0 font-display text-[32px] font-bold tracking-tight">Sign in</h2>
              <ErrorNotice message={error} />
              <TextField name="username" label="Email or username" autoComplete="username" />
              <TextField name="password" label="Password" type="password" autoComplete="current-password" />
              <Button type="submit" disabled={isSubmitting} className="min-h-12 text-base">
                {isSubmitting ? 'Signing in…' : 'Sign in'}
              </Button>
              <p className="m-0 text-center text-[15px] text-muted">
                New to Lumora Support?{' '}
                <Link to="/register" className="font-semibold text-forest">
                  Create an account
                </Link>
              </p>
            </Form>
          )}
        </Formik>
      </main>
    </div>
  )
}
