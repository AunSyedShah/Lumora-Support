import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, tokens } from '../api/client'
import { AuthContext } from './context'

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(tokens.access || tokens.refresh))

  // Restore the session after a page reload (an expired access token is refreshed by the API client).
  useEffect(() => {
    if (!tokens.access && !tokens.refresh) return
    api
      .get('/auth/me')
      .then((response) => setUser(response.data))
      .catch(() => tokens.clear())
      .finally(() => setLoading(false))
  }, [])

  // The API client signals when the refresh token has expired too.
  useEffect(() => {
    const signOut = () => setUser(null)
    window.addEventListener('auth:expired', signOut)
    return () => window.removeEventListener('auth:expired', signOut)
  }, [])

  const login = useCallback(async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password })
    tokens.save(data)
    const me = await api.get('/auth/me')
    setUser(me.data)
    return me.data
  }, [])

  const register = useCallback(
    async (fields) => {
      const { data } = await api.post('/auth/register', fields)
      return login(data.username, fields.password) // the username may have been made from the email
    },
    [login],
  )

  const logout = useCallback(() => {
    tokens.clear()
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, register, logout }), [user, loading, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
