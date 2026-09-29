import { useState } from 'react'

import { api, errorMessage } from '../api/client'
import { PaperclipIcon } from './icons'

/**
 * A complaint's files as buttons that open them in a new tab. The file needs the sign-in token,
 * so it is fetched first and then shown from memory (a plain link would not be signed in).
 */
export default function Attachments({ complaintId, files }) {
  const [error, setError] = useState('')
  if (!files?.length) return null

  async function open(file) {
    setError('')
    const tab = window.open('', '_blank') // opened straight away so the browser doesn't block it
    try {
      const { data } = await api.get(`/complaints/${complaintId}/attachments/${file.id}`, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      if (tab) tab.location.href = url
      else window.location.assign(url)
    } catch (e) {
      tab?.close()
      setError(`${file.original_filename} could not be opened: ${errorMessage(e)}`)
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap gap-2 text-sm">
        {files.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => open(f)}
            title="Open in a new tab"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border-0 bg-sand px-3 py-1.5 text-sm text-ink underline-offset-4 hover:bg-sand-2 hover:underline"
          >
            <PaperclipIcon size={16} />
            {f.original_filename}
          </button>
        ))}
      </div>
      {error && <p className="m-0 text-sm font-semibold text-rust">{error}</p>}
    </div>
  )
}
