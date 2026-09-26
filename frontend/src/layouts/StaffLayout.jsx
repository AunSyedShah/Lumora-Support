import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/context'
import Logo from '../components/Logo'
import { ChartIcon, ClockIcon, ListIcon, QueueIcon, ReportIcon, SearchIcon, SettingsIcon, SignOutIcon } from '../components/icons'
import { initials } from '../lib/format'
import { ROLE } from '../lib/labels'

// Which rail items each role sees. The API enforces the same rules; this only hides dead ends.
const ITEMS = [
  { to: '/overview', label: 'Overview', icon: ChartIcon, roles: ['manager', 'admin'] },
  { to: '/work', label: 'My queue', icon: QueueIcon, roles: ['agent'], end: true },
  { to: '/work/follow-ups', label: 'Follow-ups', icon: ClockIcon, roles: ['agent'] },
  { to: '/review', label: 'Second look', icon: SearchIcon, roles: ['reviewer', 'manager', 'admin'] },
  { to: '/complaints', label: 'Complaints', icon: ListIcon, roles: ['reviewer', 'manager', 'admin'] },
  { to: '/reports', label: 'Reports', icon: ReportIcon, roles: ['reviewer', 'manager', 'admin'] },
  { to: '/settings', label: 'Settings', icon: SettingsIcon, roles: ['admin'] },
]

const itemClass = ({ isActive }) =>
  `flex w-[68px] flex-col items-center gap-1 rounded-[14px] px-1 py-2.5 text-[11px] font-medium no-underline ${isActive ? 'bg-forest-2 text-cream' : 'text-sage hover:bg-forest-2/60 hover:text-cream'}`

export default function StaffLayout() {
  const { user, logout } = useAuth()
  const name = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username
  return (
    <div className="grid min-h-screen grid-cols-[88px_minmax(0,1fr)] gap-6 bg-cream p-4 md:p-6">
      <nav aria-label="Main" className="sticky top-4 flex h-[calc(100vh-2rem)] flex-col items-center gap-2 rounded-[22px] bg-forest py-5 md:top-6 md:h-[calc(100vh-3rem)]">
        <div className="mb-3">
          <Logo onDark />
        </div>
        {ITEMS.filter((item) => item.roles.includes(user.role)).map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={itemClass}>
            <Icon />
            {label}
          </NavLink>
        ))}
        <div className="mt-auto flex flex-col items-center gap-2">
          <div title={`${name} · ${ROLE[user.role]}`} className="flex size-10 items-center justify-center rounded-full bg-mint text-sm font-semibold text-forest">
            {initials(name)}
          </div>
          <button type="button" onClick={logout} aria-label="Sign out" title="Sign out" className="flex size-11 cursor-pointer items-center justify-center rounded-[14px] border-0 bg-transparent text-sage hover:bg-forest-2 hover:text-cream">
            <SignOutIcon />
          </button>
        </div>
      </nav>
      <main className="min-w-0 pb-10">
        <Outlet />
      </main>
    </div>
  )
}
