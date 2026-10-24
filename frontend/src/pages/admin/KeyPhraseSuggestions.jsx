import { useState } from 'react'

import { api, errorMessage } from '../../api/client'
import { Button, Card, ErrorNotice, SectionTitle } from '../../components/ui'
import { useApi } from '../../lib/useApi'

/**
 * "Teach the rules": phrases that keep showing up in complaints the rules could not recognise (or that a
 * reviewer had to reclassify), offered to the administrator. Nothing is added without a click.
 */
export default function KeyPhraseSuggestions({ problems, onAdded }) {
  const suggestions = useApi('/rules/keyword-suggestions')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [added, setAdded] = useState('')
  const list = suggestions.data || []

  async function add(s) {
    const problem = (problems || []).find((p) => p.code === s.subcategory)
    if (!problem) return setError('That problem was not found. Reload the page and try again.')
    setBusy(s.phrase)
    setError('')
    setAdded('')
    try {
      await api.patch(`/catalog/subcategories/${s.subcategory}`, { keywords: [...problem.keywords, s.phrase] })
      setAdded(`“${s.phrase}” now helps recognise ${s.subcategory_name}. It applies to new complaints straight away.`)
      suggestions.reload()
      onAdded()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy('')
    }
  }

  if (suggestions.loading && !suggestions.data) return null
  if (!list.length && !added && !suggestions.error) return null

  return (
    <Card className="flex flex-col gap-3 p-6">
      <SectionTitle>Suggested key phrases</SectionTitle>
      <p className="m-0 text-[15px] text-muted">
        These phrases appear in complaints our rules could not recognise, or that a reviewer had to move to another problem. Adding one teaches the rules for next time. Only add the ones that really point to that problem.
      </p>
      <ErrorNotice message={error || suggestions.error} />
      {added && <p className="m-0 text-[15px] font-semibold text-forest">{added}</p>}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {list.map((s) => (
          <li key={`${s.subcategory}-${s.phrase}`} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-sand px-4 py-3">
            <span className="flex min-w-0 flex-col gap-0.5 text-[15px]">
              <span>
                <strong>“{s.phrase}”</strong> → {s.subcategory_name}
              </span>
              <span className="text-[13px] text-muted">
                Seen in {s.seen_in} complaints ({s.examples.join(', ')})
                {s.also_in_other_problems > 0 ? `, and in ${s.also_in_other_problems} about other problems` : ', none about other problems'}
              </span>
            </span>
            <Button variant="light" onClick={() => add(s)} disabled={Boolean(busy)}>
              {busy === s.phrase ? 'Adding…' : 'Add this phrase'}
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
