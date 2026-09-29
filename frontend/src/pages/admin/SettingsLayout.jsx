import { NavLink, Outlet } from 'react-router-dom'

import { PageTitle } from '../../components/ui'

const TABS = [
  ['/settings/policies', 'Policies'],
  ['/settings/rules', 'Rules'],
  ['/settings/catalog', 'Problem types & teams'],
  ['/settings/products', 'Products'],
  ['/settings/assistant', 'Assistant instructions'],
  ['/settings/people', 'People'],
]

const tabClass = ({ isActive }) =>
  `rounded-full px-4 py-2 text-[15px] no-underline ${isActive ? 'bg-forest font-semibold text-white' : 'bg-white text-ink hover:bg-sand'}`

export default function SettingsLayout() {
  return (
    <div className="flex flex-col gap-5">
      <PageTitle eyebrow="Changes apply to new complaints straight away" title="Settings" />
      <nav aria-label="Settings" className="flex flex-wrap gap-2">
        {TABS.map(([to, label]) => (
          <NavLink key={to} to={to} className={tabClass}>
            {label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  )
}
