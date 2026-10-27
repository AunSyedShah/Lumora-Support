import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Badge, Button, Card, ConfirmDialog, ErrorNotice, Loading, SectionTitle, SuccessNotice } from '../../components/ui'
import { formatDateTime } from '../../lib/format'
import { reviewReason } from '../../lib/labels'
import { useApi } from '../../lib/useApi'
import { fieldLabel, input } from './style'

const WEIGHTS = [
  ['critical', 'Critical finding'],
  ['major', 'Important finding'],
  ['minor', 'Small finding'],
]
const REASON_TYPE = {
  critical_finding: 'A critical finding',
  low_score: 'Low score',
  ambiguous_complaint: 'Can’t classify',
  eligibility_unclear: 'Facts missing',
  missing_policy_support: 'No policy covers it',
  policy_contradiction: 'Older policy used',
  sensitive_complaint: 'Sensitive case',
  possible_manipulation: 'Manipulation',
  required_by_settings: 'Always checked (your setting)',
  genai_output_invalid: 'AI failed',
  processing_failed: 'Processing failed',
}

const toggle = (list, value) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

function Check({ checked, onChange, children, disabled, hint }) {
  return (
    <label className={`flex items-start gap-3 rounded-2xl bg-sand px-4 py-2.5 text-[15px] ${disabled ? 'opacity-70' : 'cursor-pointer'}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="mt-1 size-4 accent-forest" />
      <span className="flex flex-col">
        <span className="font-semibold">{children}</span>
        {hint && <span className="text-[13px] font-normal text-muted">{hint}</span>}
      </span>
    </label>
  )
}

function PreviewResult({ p }) {
  const worse = p.must_review_caught_after < p.must_review_caught_now
  return (
    <div className="flex flex-col gap-3 rounded-2xl border-[1.5px] border-line bg-white p-5" aria-live="polite">
      <p className="m-0 text-[17px]">
        Of the <strong>{p.checked}</strong> complaints checked so far, <strong>{p.review_now}</strong> went to a second look. With these settings it would be{' '}
        <strong className={p.review_after < p.review_now ? 'text-forest' : ''}>{p.review_after}</strong>
        {p.no_longer_review > 0 && <> ({p.no_longer_review} fewer)</>}
        {p.newly_review > 0 && <> ({p.newly_review} more)</>}.
      </p>
      {p.must_review > 0 && (
        <p className={`m-0 rounded-xl px-4 py-2.5 text-[15px] ${worse ? 'bg-sun-soft text-rust' : 'bg-mint'}`}>
          <strong>Safety check:</strong> {p.must_review} sample complaints should always go to a person (unclear, manipulation attempts, missing information). Now{' '}
          {p.must_review_caught_now} do; with these settings {p.must_review_caught_after} would. {worse ? 'Some would be missed. Reconsider before saving.' : 'None would be missed.'}
        </p>
      )}
      {Object.keys(p.reasons_after).length > 0 && (
        <p className="m-0 text-[14px] text-muted">
          Reasons with these settings:{' '}
          {Object.entries(p.reasons_after)
            .sort((a, b) => b[1] - a[1])
            .map(([k, n]) => `${REASON_TYPE[k] || k} ${n}`)
            .join(' · ')}
        </p>
      )}
      {[
        ['Would no longer need a person', p.dropped_examples],
        ['Would newly need a person', p.added_examples],
      ].map(([title, rows]) =>
        rows.length > 0 ? (
          <details key={title}>
            <summary className="cursor-pointer text-[14px] font-semibold text-forest">{title} (examples)</summary>
            <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0 text-[14px]">
              {rows.map((r) => (
                <li key={r.complaint_id} className="rounded-xl bg-sand px-3 py-2">
                  <strong>{r.complaint_id}</strong> · {r.title}
                  <br />
                  <span className="text-muted">{r.reasons.map(reviewReason).join(' · ')}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null,
      )}
    </div>
  )
}

function Editor({ state, onSaved }) {
  const [form, setForm] = useState(state.active.settings)
  const [comment, setComment] = useState('')
  const [preview, setPreview] = useState(null) // { for: JSON of the form it was run on, data }
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const key = JSON.stringify(form)
  const changed = key !== JSON.stringify(state.active.settings)
  const previewed = preview && preview.for === key
  const set = (patch) => setForm({ ...form, ...patch })
  const number = (value) => (value === '' ? '' : Number(value))

  async function run() {
    setBusy('preview')
    setError('')
    try {
      const { data } = await api.post('/validation/review-policy/preview', { settings: form })
      setPreview({ for: key, data })
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy('')
    }
  }

  async function save() {
    setBusy('save')
    setError('')
    try {
      const { data } = await api.post('/validation/review-policy', { settings: form, comment })
      onSaved(data, `Saved as version ${data.active.version}. It applies to the next complaints.`)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <Card className="flex flex-col gap-6 p-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="flex flex-col gap-3">
          <h3 className="m-0 text-[17px] font-semibold">Score</h3>
          <p className="m-0 text-[14px] text-muted">Every complaint starts at 100. Each difference between the AI’s suggestion and our rules takes points off. Below the cutoff, a person looks.</p>
          <label className={fieldLabel}>
            Cutoff ({state.bounds.score_threshold[0]}–{state.bounds.score_threshold[1]})
            <input type="number" min={state.bounds.score_threshold[0]} max={state.bounds.score_threshold[1]} value={form.score_threshold} onChange={(e) => set({ score_threshold: number(e.target.value) })} className={`${input} max-w-32`} />
          </label>
          <div className="grid grid-cols-3 gap-3">
            {WEIGHTS.map(([k, label]) => (
              <label key={k} className={fieldLabel}>
                {label} costs
                <input type="number" min={state.bounds.penalty[0]} max={state.bounds.penalty[1]} value={form.penalty[k]} onChange={(e) => set({ penalty: { ...form.penalty, [k]: number(e.target.value) } })} className={input} />
              </label>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="m-0 text-[17px] font-semibold">What sends a complaint to a person</h3>
          {state.triggers.map((t) => (
            <Check key={t.key} checked={form.triggers[t.key]} onChange={(on) => set({ triggers: { ...form.triggers, [t.key]: on } })}>
              {t.label}
            </Check>
          ))}
          <Check
            checked={form.ignore_corrected_criticals}
            onChange={(on) => set({ ignore_corrected_criticals: on })}
            hint={`The final plan already fixes these by itself: ${state.corrected_by_rules.join(', ')}. Anything else the AI got wrong (a forbidden action, an invented fact, a wrong problem type) still goes to a person.`}
          >
            Don’t count a critical finding the rules already corrected
          </Check>
        </section>
      </div>

      <section className="flex flex-col gap-2">
        <h3 className="m-0 text-[17px] font-semibold">Also treat these as sensitive</h3>
        <p className="m-0 text-[14px] text-muted">Compliance review and critical management are always sensitive. Add more if you want:</p>
        <div className="flex flex-wrap gap-2">
          {state.optional_sensitive_levels.map((l) => (
            <Check key={l.value} checked={form.sensitive_levels.includes(l.value)} onChange={() => set({ sensitive_levels: toggle(form.sensitive_levels, l.value) })}>
              {l.label}
            </Check>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="m-0 text-[17px] font-semibold">Always check these problem types</h3>
        <div className="flex flex-wrap gap-2">
          {state.categories.map((c) => (
            <Check key={c.code} checked={form.always_review_categories.includes(c.code)} onChange={() => set({ always_review_categories: toggle(form.always_review_categories, c.code) })}>
              {c.name}
            </Check>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2 rounded-2xl bg-mint px-5 py-4">
        <h3 className="m-0 text-[15px] font-semibold">Always on — these can’t be switched off</h3>
        <ul className="m-0 flex flex-col gap-1 pl-5 text-[14px]">
          {state.always_on.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>

      <ErrorNotice message={error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={run} disabled={Boolean(busy)}>
          {busy === 'preview' ? 'Checking…' : 'See what would change'}
        </Button>
        <Button variant="ghost" onClick={() => setForm(state.defaults)} disabled={Boolean(busy)}>
          Reset the form to the built-in defaults
        </Button>
      </div>
      {previewed && <PreviewResult p={preview.data} />}

      <div className="flex flex-col gap-2 border-t border-line-soft pt-5">
        <label className={fieldLabel}>
          Why are you changing it? (kept with the version)
          <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Too many complaints waiting for a second look" maxLength={300} className={input} />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={save} disabled={Boolean(busy) || !changed || !previewed || comment.trim().length < 5}>
            {busy === 'save' ? 'Saving…' : `Save as version ${(state.history[0]?.version || 0) + 1}`}
          </Button>
          <span className="text-[13px] text-muted">{!changed ? 'Nothing is different yet.' : !previewed ? 'Look at “what would change” first.' : comment.trim().length < 5 ? 'Add a reason.' : 'It applies to the next complaints, not to ones already decided.'}</span>
        </div>
      </div>
    </Card>
  )
}

export default function ReviewRules() {
  const state = useApi('/validation/review-policy')
  const [message, setMessage] = useState('')
  const [back, setBack] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (state.loading && !state.data) return <Loading />
  if (!state.data) return <ErrorNotice message={state.error} onRetry={state.reload} />
  const s = state.data

  async function rollback() {
    setBusy(true)
    setError('')
    try {
      await api.post(`/validation/review-policy/${back.version}/rollback`, { comment: reason })
      setMessage(`Using version ${back.version}’s rules again (saved as a new version).`)
      setBack(null)
      setReason('')
      state.reload()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Card className="flex flex-col gap-2 p-6">
        <SectionTitle>Second-look rules</SectionTitle>
        <p className="m-0 text-[15px] text-muted">
          Which complaints a person must check before anything goes out. A change makes a new version and applies to the next complaints; older versions are kept, and every decision remembers the version it used.
        </p>
        <p className="m-0 text-[15px]">
          In use: <strong>{s.active.version === 0 ? 'built-in defaults' : `version ${s.active.version}`}</strong>
          {s.active.created_at && <span className="text-muted"> · {s.active.created_by_name || 'someone'} · {formatDateTime(s.active.created_at)} · “{s.active.comment}”</span>}
        </p>
        <SuccessNotice>{message}</SuccessNotice>
      </Card>

      <Editor key={s.active.version} state={s} onSaved={(data, text) => { setMessage(text); state.reload() }} />

      <Card className="flex flex-col gap-3 p-6">
        <SectionTitle>History</SectionTitle>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {s.history.map((h) => (
            <li key={h.version} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-sand px-4 py-3 text-[15px]">
              <span className="flex flex-col">
                <span className="flex items-center gap-2 font-semibold">
                  Version {h.version} {h.is_active && <Badge tone="green">In use</Badge>}
                </span>
                <span className="text-[13px] text-muted">
                  {h.created_by_name || 'someone'} · {formatDateTime(h.created_at)} · cutoff {h.settings.score_threshold}
                  {h.settings.ignore_corrected_criticals ? ' · skips corrected findings' : ''}
                  {h.settings.always_review_categories.length ? ` · always checks ${h.settings.always_review_categories.length} problem type(s)` : ''}
                </span>
                <span>{h.comment}</span>
              </span>
              {!h.is_active && (
                <Button variant="light" onClick={() => { setError(''); setReason(''); setBack(h) }}>
                  Use this version again
                </Button>
              )}
            </li>
          ))}
          <li className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-sand px-4 py-3 text-[15px]">
            <span className="flex flex-col">
              <span className="font-semibold">Built-in defaults</span>
              <span className="text-[13px] text-muted">How it worked before anything was changed: cutoff {s.defaults.score_threshold}, every trigger on.</span>
            </span>
            {s.active.version !== 0 && (
              <Button variant="light" onClick={() => { setError(''); setReason(''); setBack({ version: 0 }) }}>
                Use the defaults again
              </Button>
            )}
          </li>
        </ul>
      </Card>

      <ConfirmDialog
        open={Boolean(back)}
        title={back?.version === 0 ? 'Go back to the built-in defaults?' : `Use version ${back?.version} again?`}
        confirmLabel="Use it again"
        cancelLabel="Cancel"
        busyLabel="Saving…"
        variant="primary"
        busy={busy}
        error={error}
        onConfirm={rollback}
        onCancel={() => setBack(null)}
      >
        <p className="m-0">It becomes the rules for the next complaints. Nothing already decided changes.</p>
        <label className={fieldLabel}>
          Why? (kept with the version)
          <input value={reason} onChange={(e) => setReason(e.target.value)} className={input} maxLength={300} />
        </label>
      </ConfirmDialog>
    </div>
  )
}
