/* Simple stroke icons (inline SVG, inherit the text colour). */
function Icon({ children, size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  )
}

export const QueueIcon = (p) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h10" />
  </Icon>
)
export const ClockIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 8v4l3 2" />
  </Icon>
)
export const SearchIcon = (p) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="6" />
    <path d="M20 20l-4.5-4.5" />
  </Icon>
)
export const ChartIcon = (p) => (
  <Icon {...p}>
    <path d="M5 20V11M12 20V5M19 20v-7" />
  </Icon>
)
export const ListIcon = (p) => (
  <Icon {...p}>
    <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />
  </Icon>
)
export const ReportIcon = (p) => (
  <Icon {...p}>
    <path d="M6 4h9l3 3v13H6z" />
    <path d="M9 11h6M9 15h6" />
  </Icon>
)
export const SettingsIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />
  </Icon>
)
export const CheckIcon = (p) => (
  <Icon {...p}>
    <path d="M5 12l4 4 10-10" />
  </Icon>
)
export const AlertIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v5M12 16h.01" />
  </Icon>
)
export const SignOutIcon = (p) => (
  <Icon {...p}>
    <path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" />
  </Icon>
)
export const PaperclipIcon = (p) => (
  <Icon {...p}>
    <path d="M20 11l-8.5 8.5a5 5 0 01-7-7L13 4a3.5 3.5 0 015 5l-8.5 8.5a2 2 0 01-3-3L14 7" />
  </Icon>
)
