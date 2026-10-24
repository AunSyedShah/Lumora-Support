import { useState } from 'react'

import { api, errorMessage } from '../api/client'
import { useAuth } from '../auth/context'
import { formatDateTime } from '../lib/format'
import { useAiStatus } from '../lib/useAiStatus'
import { AlertIcon, CheckIcon } from './icons'
import { Button, Card, ErrorNotice, SectionTitle } from './ui'

// What an administrator can do about each kind of failure (staff only get told who to ask).
const FIX = {
  balance: 'Top up the DeepSeek account (platform.deepseek.com, Top up), then press “Check again”.',
  auth: 'Put a valid key in DEEPSEEK_API_KEY and restart the backend. On Vercel: Settings, Environment Variables, then redeploy.',
  not_configured: 'Set DEEPSEEK_API_KEY in the .env file and restart the backend. On Vercel: Settings, Environment Variables, then redeploy.',
  rate_limit: 'This usually clears within a minute. If it keeps happening, check the request limits of the DeepSeek account.',
  unreachable: 'Check the server’s internet connection. The next complaint tries again by itself.',
  unavailable: 'DeepSeek is having an outage (status.deepseek.com). The next complaint tries again by itself.',
  rejected: 'Check DEEPSEEK_MODEL and DEEPSEEK_BASE_URL in the settings.',
}

/** Sends one tiny real request to the provider (administrators) and refreshes the status. */
function useCheck(reload) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function check() {
    setBusy(true)
    setError('')
    try {
      await api.post('/genai/check')
      reload()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, check }
}

/** Shown on every staff page, but only while the AI assistant is not working. */
export function AiStatusBanner() {
  const { user } = useAuth()
  const status = useAiStatus()
  const { busy, error, check } = useCheck(status.reload)
  const s = status.data
  if (!s || s.ok) return null
  const isAdmin = user.role === 'admin'
  return (
    <div role="alert" className="mb-5 flex flex-col gap-2 rounded-2xl bg-sun-soft px-5 py-4 text-sun-ink">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0 text-rust">
          <AlertIcon size={22} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <strong>{s.message}</strong>
          <span className="text-[15px]">
            New complaints are still sorted and sent to the right team by our rules, and wait for a person to check them. Draft replies are not written until it works again.
          </span>
          <span className="text-[15px]">{isAdmin ? FIX[s.kind] || 'Check the AI settings, then press “Check again”.' : 'Please tell an administrator.'}</span>
          {s.since && <span className="text-[13px] opacity-75">Since {formatDateTime(s.since)}</span>}
        </div>
        {isAdmin && (
          <Button variant="light" onClick={check} disabled={busy} className="shrink-0">
            {busy ? 'Checking…' : 'Check again'}
          </Button>
        )}
      </div>
      <ErrorNotice message={error} />
    </div>
  )
}

/** Settings, Assistant instructions: is the connection to the AI provider working right now? */
export function AiConnectionCard() {
  const status = useAiStatus()
  const { busy, error, check } = useCheck(status.reload)
  const s = status.data
  return (
    <Card className="flex flex-col gap-3 p-6 xl:col-span-2">
      <SectionTitle>Connection to the AI service</SectionTitle>
      {!s && <p className="m-0 text-[15px] text-muted">Checking…</p>}
      {s?.ok && (
        <p className="m-0 flex items-center gap-2 text-[15px]">
          <span className="text-forest">
            <CheckIcon size={20} />
          </span>
          No problems seen{s.since ? ` (last used ${formatDateTime(s.since)})` : ''}.
        </p>
      )}
      {s && !s.ok && (
        <div className="flex flex-col gap-1.5 rounded-2xl bg-sun-soft px-4 py-3 text-[15px] text-sun-ink">
          <strong>{s.message}</strong>
          <span>{FIX[s.kind] || 'Check the AI settings, then press “Check connection”.'}</span>
        </div>
      )}
      <ErrorNotice message={error || status.error} />
      <Button variant="light" className="self-start" onClick={check} disabled={busy}>
        {busy ? 'Checking…' : 'Check connection'}
      </Button>
      <p className="m-0 text-[13px] text-muted">Sends one very small request to the AI service to test the key, the balance and the connection.</p>
    </Card>
  )
}
