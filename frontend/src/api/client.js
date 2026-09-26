/*
 * One axios instance for the whole app.
 *  - every request goes to /api/... (Vite forwards it to Django in development)
 *  - the access token is added automatically
 *  - when the access token has expired (401), the refresh token gets a new one once and the
 *    request is retried; if that fails too, the user is signed out
 */
import axios from 'axios'

const ACCESS_KEY = 'sn_access'
const REFRESH_KEY = 'sn_refresh'

function read(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export const tokens = {
  get access() {
    return read(ACCESS_KEY)
  },
  get refresh() {
    return read(REFRESH_KEY)
  },
  save({ access, refresh }) {
    try {
      localStorage.setItem(ACCESS_KEY, access)
      if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
    } catch {
      // storage blocked (private mode): the session lasts until the page is closed
    }
  },
  clear() {
    try {
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
    } catch {
      // nothing stored
    }
  },
}

export const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const access = tokens.access
  if (access) config.headers.Authorization = `Bearer ${access}`
  return config
})

let refreshing = null // one refresh at a time, shared by requests that fail together

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const expired = error.response?.status === 401 && !original?._retried && !original?.url?.startsWith('/auth/')
    if (expired && tokens.refresh) {
      original._retried = true
      refreshing ??= axios
        .post('/api/auth/refresh', { refresh: tokens.refresh })
        .then((response) => tokens.save(response.data))
        .finally(() => {
          refreshing = null
        })
      try {
        await refreshing
        return api(original)
      } catch {
        tokens.clear()
        window.dispatchEvent(new Event('auth:expired'))
      }
    }
    return Promise.reject(error)
  },
)

/** A sentence to show the user for any failed request. */
export function errorMessage(error, fallback = 'Something went wrong. Please try again.') {
  if (!error?.response) return 'We can’t reach the server right now. Please check your connection and try again.'
  const detail = error.response.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // Django Ninja validation errors: [{loc: [...], msg: "..."}]
    return detail.map((d) => d.msg?.replace(/^Value error, /, '')).filter(Boolean).join(' ') || fallback
  }
  return fallback
}

/** Download a file the API returns (reports, exports) and save it with the server's file name. */
export async function downloadFile(url, params, fallbackName) {
  const response = await api.get(url, { params, responseType: 'blob' })
  const disposition = response.headers['content-disposition'] || ''
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] || fallbackName
  const link = document.createElement('a')
  link.href = URL.createObjectURL(response.data)
  link.download = name
  link.click()
  URL.revokeObjectURL(link.href)
}
