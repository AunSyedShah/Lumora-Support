/* Small building blocks in the Homey style. Pages combine these with Tailwind classes. */
import { useField, useFormikContext } from 'formik'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'

import { AlertIcon } from './icons'

const BUTTON = {
  primary: 'bg-forest text-white hover:bg-forest-2 border-transparent',
  outline: 'bg-transparent text-forest border-forest hover:bg-mint',
  ghost: 'bg-transparent text-forest border-transparent underline underline-offset-4 hover:bg-mint',
  light: 'bg-white text-forest border-line hover:bg-mint',
  danger: 'bg-rust text-white hover:bg-[#6f2e0e] border-transparent',
}

export function Button({ variant = 'primary', to, className = '', children, ...props }) {
  const classes = `inline-flex min-h-11 items-center justify-center gap-2 rounded-full border-[1.5px] px-5 py-2.5 text-[15px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON[variant]} ${className}`
  if (to) {
    return (
      <Link to={to} className={`${classes} no-underline`} {...props}>
        {children}
      </Link>
    )
  }
  return (
    <button type="button" className={classes} {...props}>
      {children}
    </button>
  )
}

/**
 * A confirmation pop-up in the app's own style (replaces the browser's confirm box).
 * Built on the native <dialog>: Esc closes it, focus stays inside, the page behind is dimmed.
 * The safe button ("Keep it") has the initial focus, so a stray Enter never deletes anything.
 */
export function ConfirmDialog({ open, title, confirmLabel = 'Delete', cancelLabel = 'Keep it', busyLabel = 'Deleting…', variant = 'danger', busy = false, error, onConfirm, onCancel, children }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault() // Esc: let the page decide, so a delete in progress is not interrupted
        if (!busy) onCancel()
      }}
      onClick={(e) => e.target === ref.current && !busy && onCancel()} // a click on the dimmed area
      className="m-auto w-[min(92vw,30rem)] rounded-[26px] border-0 bg-white p-0 text-ink shadow-[0_24px_64px_rgba(31,42,36,0.28)] backdrop:bg-ink/45 backdrop:backdrop-blur-[2px]"
    >
      {open && (
        <div className="flex flex-col gap-4 p-7">
          <div className="flex items-start gap-4">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-sun-soft text-rust">
              <AlertIcon size={24} />
            </span>
            <div className="flex min-w-0 flex-col gap-2">
              <h2 id="confirm-title" className="m-0 font-display text-[22px] leading-tight font-bold tracking-tight">
                {title}
              </h2>
              <div className="flex flex-col gap-2 text-[15px] leading-relaxed text-muted">{children}</div>
            </div>
          </div>
          {error && <p role="alert" className="m-0 rounded-xl bg-sun-soft px-4 py-2.5 text-[15px] text-rust">{error}</p>}
          <div className="flex flex-wrap justify-end gap-2.5 pt-1">
            <Button variant="light" onClick={onCancel} disabled={busy} autoFocus>
              {cancelLabel}
            </Button>
            <Button variant={variant} onClick={onConfirm} disabled={busy}>
              {busy ? busyLabel : confirmLabel}
            </Button>
          </div>
        </div>
      )}
    </dialog>
  )
}

export function Card({ as: Tag = 'section', className = '', children, ...props }) {
  return (
    <Tag className={`rounded-[26px] bg-white p-7 ${className}`} {...props}>
      {children}
    </Tag>
  )
}

const BADGE = {
  green: 'bg-mint text-forest',
  sun: 'bg-sun text-sun-ink',
  soft: 'bg-sun-soft text-sun-ink',
  sand: 'bg-sand-2 text-muted',
  dark: 'bg-forest text-white',
  outline: 'bg-white text-ink border border-line',
  warn: 'bg-sun-soft text-rust',
}

export function Badge({ tone = 'sand', className = '', children }) {
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold whitespace-nowrap ${BADGE[tone]} ${className}`}>
      {children}
    </span>
  )
}

export function PageTitle({ eyebrow, title, children }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1">
        {eyebrow && <p className="m-0 text-[15px] text-muted">{eyebrow}</p>}
        <h1 className="m-0 font-display text-[32px] leading-tight font-bold tracking-tight">{title}</h1>
      </div>
      {children && <div className="flex flex-wrap items-center gap-3">{children}</div>}
    </div>
  )
}

export function SectionTitle({ children, className = '' }) {
  return <h2 className={`m-0 font-display text-xl font-bold ${className}`}>{children}</h2>
}

export function Loading({ label = 'Loading…' }) {
  return (
    <div role="status" className="flex items-center gap-3 p-8 text-muted">
      <span className="size-5 animate-spin rounded-full border-2 border-line border-t-forest" aria-hidden="true" />
      {label}
    </div>
  )
}

export function ErrorNotice({ message, onRetry }) {
  const box = useRef(null)
  // Errors often appear above a long form: bring them into view so they are not missed.
  useEffect(() => {
    if (message) box.current?.scrollIntoView({ block: 'center' })
  }, [message])
  if (!message) return null
  return (
    <div ref={box} role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl bg-sun-soft px-5 py-4 text-sun-ink">
      <span className="flex-1">{message}</span>
      {onRetry && (
        <Button variant="light" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function SuccessNotice({ children }) {
  if (!children) return null
  return (
    <div role="status" className="rounded-2xl bg-mint px-5 py-4 text-forest">
      {children}
    </div>
  )
}

export function EmptyState({ title, children }) {
  return (
    <div className="flex flex-col gap-2 rounded-[26px] border-[1.5px] border-dashed border-line p-8 text-center">
      <p className="m-0 font-display text-lg font-bold">{title}</p>
      {children && <p className="m-0 text-muted">{children}</p>}
    </div>
  )
}

/* ---------- form fields (Formik) ---------- */

/** After a send with mistakes, move to the first field that needs fixing. Put it inside <Form>. */
export function FocusFirstError() {
  const { submitCount, isSubmitting, errors } = useFormikContext()
  const handled = useRef(0)
  useEffect(() => {
    // wait until Formik has finished checking the fields for this attempt
    if (isSubmitting || submitCount === handled.current) return
    handled.current = submitCount
    const first = Object.keys(errors)[0]
    const field = first && document.querySelector(`[name="${first}"]`)
    if (field) {
      field.scrollIntoView({ block: 'center', behavior: 'smooth' }) // keep its label in view too
      field.focus({ preventScroll: true })
    }
  }, [submitCount, isSubmitting, errors])
  return null
}

const INPUT = 'w-full rounded-[14px] border-[1.5px] border-line bg-white px-4 py-3 text-base text-ink placeholder:text-muted/70 focus:border-forest focus:outline-none'

function FieldShell({ id, label, hint, error, children }) {
  return (
    <div className="flex flex-col gap-2">
      {label && (
        <label htmlFor={id} className="text-[15px] font-semibold">
          {label} {hint && <span className="font-normal text-muted">{hint}</span>}
        </label>
      )}
      {children}
      {error && <p className="m-0 text-sm font-semibold text-rust">{error}</p>}
    </div>
  )
}

export function TextField({ label, hint, ...props }) {
  const [field, meta] = useField(props)
  const id = props.id || props.name
  const error = meta.touched && meta.error
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <input id={id} className={INPUT} aria-invalid={Boolean(error)} {...field} {...props} />
    </FieldShell>
  )
}

export function TextArea({ label, hint, rows = 4, ...props }) {
  const [field, meta] = useField(props)
  const id = props.id || props.name
  const error = meta.touched && meta.error
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <textarea id={id} rows={rows} className={`${INPUT} resize-y leading-relaxed`} aria-invalid={Boolean(error)} {...field} {...props} />
    </FieldShell>
  )
}

export function SelectField({ label, hint, options, ...props }) {
  const [field, meta] = useField(props)
  const id = props.id || props.name
  const error = meta.touched && meta.error
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <select id={id} className={INPUT} aria-invalid={Boolean(error)} {...field} {...props}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldShell>
  )
}

/** Pill-shaped radio buttons ("How should we get back to you?"). */
export function PillChoice({ name, legend, options }) {
  const [field] = useField(name)
  return (
    <fieldset className="m-0 flex flex-col gap-3 border-0 p-0">
      <legend className="mb-3 p-0 text-[15px] font-semibold">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const checked = field.value === o.value
          return (
            <label
              key={o.value}
              className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-full border-[1.5px] px-4 text-[15px] ${checked ? 'border-forest bg-mint' : 'border-line bg-white'}`}
            >
              <input type="radio" name={name} value={o.value} checked={checked} onChange={field.onChange} className="accent-forest" />
              {o.label}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

/** Plain controlled inputs for filters and small forms that don't need Formik. */
export function Select({ label, value, onChange, options, className = '' }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 text-[13px] text-muted ${className}`}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="max-w-full rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] text-ink focus:border-forest focus:outline-none">
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

