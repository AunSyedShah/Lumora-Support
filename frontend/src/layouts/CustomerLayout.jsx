import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/context'
import Logo from '../components/Logo'
import { Button } from '../components/ui'

const linkClass = ({ isActive }) =>
  `rounded-full px-4 py-2 text-[15px] no-underline ${isActive ? 'bg-forest font-semibold text-white' : 'text-ink hover:bg-sand'}`

export default function CustomerLayout() {
  const { user, logout } = useAuth()
  const name = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username
  return (
    <div className="min-h-screen bg-cream">
      <header className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-x-8 gap-y-3 px-5 py-4 md:px-10 md:py-5">
        <NavLink to="/my/complaints" aria-label="Lumora Support home" className="flex items-center gap-2.5 text-ink no-underline">
          <Logo size="sm" />
          <span className="hidden font-display text-[19px] font-bold sm:inline">Lumora Support</span>
        </NavLink>
        <nav aria-label="Main" className="order-3 flex w-full gap-1.5 sm:order-none sm:w-auto">
          <NavLink to="/my/complaints" className={linkClass}>
            My complaints
          </NavLink>
          <NavLink to="/my/orders" className={linkClass}>
            My orders
          </NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-3 sm:gap-4">
          <Button variant="outline" to="/my/complaints/new">
            New complaint
          </Button>
          <span className="hidden text-[15px] text-muted sm:inline">{name}</span>
          <button type="button" onClick={logout} className="cursor-pointer border-0 bg-transparent text-[15px] text-forest underline underline-offset-4">
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-[1280px] px-5 pb-12 md:px-10">
        <Outlet />
      </main>
    </div>
  )
}
