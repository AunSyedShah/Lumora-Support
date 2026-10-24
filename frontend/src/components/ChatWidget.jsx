import { useEffect, useRef, useState } from 'react'

import { api, errorMessage } from '../api/client'
import { useApi } from '../lib/useApi'
import { Button } from './ui'

const GREETING = 'Hi! I can answer general questions about our policies — returns, refunds, delivery, warranty, LumoraCare+ and more. I can’t see your orders or account.'
const SUGGESTIONS = ['How do I return a device?', 'When do I get a refund?', 'How long does delivery take?']
const HISTORY_TURNS = 6

/**
 * A small chat for general questions, answered from the company documents. Only shown while an
 * administrator has switched it on. It keeps the conversation in this page only.
 */
export default function ChatWidget() {
  const status = useApi('/chatbot/status')
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef(null)

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages, busy, open])

  if (!status.data?.enabled) return null

  async function send(question) {
    const q = question.trim()
    if (!q || busy) return
    const history = messages.filter((m) => !m.failed).map((m) => ({ role: m.role, text: m.text })).slice(-HISTORY_TURNS)
    setMessages((m) => [...m, { role: 'user', text: q }])
    setText('')
    setBusy(true)
    try {
      const { data } = await api.post('/chatbot/chat', { question: q, history })
      setMessages((m) => [...m, { role: 'assistant', text: data.answer, sources: data.sources, complaint: data.suggest_complaint }])
    } catch (e) {
      if (e.response?.status === 403) status.reload() // switched off while the chat was open
      setMessages((m) => [...m, { role: 'assistant', text: errorMessage(e), failed: true, complaint: true }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed right-4 bottom-4 z-40 flex flex-col items-end gap-3 sm:right-6 sm:bottom-6">
      {open && (
        <section aria-label="Chat with Lumora Support" className="flex h-[min(560px,calc(100vh-110px))] w-[min(380px,calc(100vw-32px))] flex-col overflow-hidden rounded-3xl border border-line bg-white shadow-xl">
          <header className="flex items-center justify-between gap-2 bg-forest px-5 py-3.5 text-white">
            <div className="flex flex-col">
              <strong className="font-display text-[17px]">Ask Lumora</strong>
              <span className="text-[13px] text-white/80">Answers from our policies</span>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close chat" className="cursor-pointer rounded-full border-0 bg-transparent px-2 py-1 text-[22px] leading-none text-white hover:bg-white/15">
              ×
            </button>
          </header>

          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4" aria-live="polite">
            <p className="m-0 max-w-[88%] self-start rounded-[4px_16px_16px_16px] bg-mint px-4 py-3 text-[15px] leading-relaxed">{GREETING}</p>
            {messages.length === 0 && (
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => send(s)} className="cursor-pointer rounded-full border border-line bg-white px-3.5 py-1.5 text-[14px] text-forest hover:bg-mint">
                    {s}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex max-w-[88%] flex-col gap-1.5 ${m.role === 'user' ? 'items-end self-end' : 'items-start self-start'}`}>
                <p className={`m-0 px-4 py-3 text-[15px] leading-relaxed whitespace-pre-line ${m.role === 'user' ? 'rounded-[16px_4px_16px_16px] bg-sand' : 'rounded-[4px_16px_16px_16px] bg-mint'}`}>{m.text}</p>
                {m.sources?.length > 0 && <span className="text-[12.5px] text-muted">From: {m.sources.map((s) => s.title).join(' · ')}</span>}
                {m.complaint && (
                  <Button variant="light" to="/my/complaints/new" className="!px-4 !py-1.5 !text-[14px]">
                    Tell us what happened
                  </Button>
                )}
              </div>
            ))}
            {busy && <p className="m-0 self-start rounded-[4px_16px_16px_16px] bg-mint px-4 py-3 text-[15px] text-muted">Looking that up…</p>}
            <div ref={end} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              send(text)
            }}
            className="flex items-end gap-2 border-t border-line-soft p-3"
          >
            <label htmlFor="chat-question" className="sr-only">
              Your question
            </label>
            <textarea
              id="chat-question"
              rows={1}
              maxLength={600}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(text)
                }
              }}
              placeholder="Type your question"
              className="max-h-28 min-h-[44px] flex-1 resize-none rounded-[14px] border-[1.5px] border-line px-3.5 py-2.5 text-[15px] focus:border-forest focus:outline-none"
            />
            <Button type="submit" disabled={busy || !text.trim()} className="!px-4">
              Send
            </Button>
          </form>
        </section>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="cursor-pointer rounded-full border-0 bg-forest px-6 py-3.5 text-[16px] font-semibold text-white shadow-lg hover:bg-forest-2"
      >
        {open ? 'Close chat' : 'Ask a question'}
      </button>
    </div>
  )
}
