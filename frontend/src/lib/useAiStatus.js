import { useEffect } from 'react'

import { useApi } from './useApi'

/** The AI provider's state, refreshed every two minutes and whenever the tab is shown again. */
export function useAiStatus() {
  const status = useApi('/genai/status')
  const { reload } = status
  useEffect(() => {
    const timer = setInterval(reload, 120000)
    const onShow = () => document.visibilityState === 'visible' && reload()
    document.addEventListener('visibilitychange', onShow)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onShow)
    }
  }, [reload])
  return status
}
