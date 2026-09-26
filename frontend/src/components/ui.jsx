/* Small building blocks in the Homey style. Pages combine these with Tailwind classes. */
import { useField } from 'formik'
import { Link } from 'react-router-dom'

const BUTTON = {
  primary: 'bg-forest text-white hover:bg-forest-2 border-transparent',
  outline: 'bg-transparent text-forest border-forest hover:bg-mint',
  ghost: 'bg-transparent text-forest border-transparent underline underline-offset-4 hover:bg-mint',
  light: 'bg-white text-forest border-line hover:bg-mint',
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
  if (!message) return null
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl bg-sun-soft px-5 py-4 text-sun-ink">
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
    <label className={`flex flex-col gap-1 text-[13px] text-muted ${className}`}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-xl border-[1.5px] border-line bg-white px-3 py-2 text-[15px] text-ink focus:border-forest focus:outline-none">
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

