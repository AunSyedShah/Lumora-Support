import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { Loading } from '../components/ui'
import { homeFor, useAuth } from './context'

/** Only lets signed-in users with one of `roles` through; everyone else is sent where they belong. */
export default function RequireRole({ roles }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <Loading label="Signing you in…" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (roles && !roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />
  return <Outlet />
}
