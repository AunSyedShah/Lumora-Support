import { createContext, useContext } from 'react'

export const AuthContext = createContext(null)

/** { user, loading, login(username, password), register(data), logout() } */
export function useAuth() {
  return useContext(AuthContext)
}

export const STAFF_ROLES = ['agent', 'reviewer', 'manager', 'admin']
export const FULL_ACCESS_ROLES = ['reviewer', 'manager', 'admin'] // see complaints/permissions.py

/** Where each role lands after signing in. */
export function homeFor(role) {
  if (role === 'customer') return '/my/complaints'
  if (role === 'agent') return '/work'
  if (role === 'reviewer') return '/review'
  return '/overview' // manager, admin
}
