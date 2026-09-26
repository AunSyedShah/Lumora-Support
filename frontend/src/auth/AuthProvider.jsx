import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, tokens } from '../api/client'
import { AuthContext } from './context'

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(tokens.access))

  // Restore the session after a page reload.
  useEffect(() => {
    if (!tokens.access) return
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
      await api.post('/auth/register', fields)
      return login(fields.username, fields.password)
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
