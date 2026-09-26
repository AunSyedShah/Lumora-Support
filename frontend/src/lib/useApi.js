import { useCallback, useEffect, useState } from 'react'

import { api, errorMessage } from '../api/client'

/**
 * Load data from a GET endpoint.
 *   const { data, error, loading, reload } = useApi('/complaints/my')
 *   useApi(id ? `/complaints/${id}` : null, { params })   // null = don't load yet
 * While reloading, the previous data stays on screen.
 */
export function useApi(url, { params } = {}) {
  const paramsKey = JSON.stringify(params ?? {})
  const [version, setVersion] = useState(0)
  const [result, setResult] = useState({ key: null, data: null, error: null })
  const requestKey = url ? `${url}?${paramsKey}#${version}` : null

  useEffect(() => {
    if (!requestKey) return undefined
    let cancelled = false
    api
      .get(url, { params: JSON.parse(paramsKey) })
      .then((response) => !cancelled && setResult({ key: requestKey, data: response.data, error: null }))
      .catch((error) => !cancelled && setResult((r) => ({ key: requestKey, data: r.data, error: errorMessage(error) })))
    return () => {
      cancelled = true
    }
  }, [url, paramsKey, requestKey])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  const loading = Boolean(requestKey) && result.key !== requestKey
  return { data: result.data, error: loading ? null : result.error, loading, reload }
}
