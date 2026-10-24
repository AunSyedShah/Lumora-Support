import { useApi } from '../lib/useApi'
import { Card, ErrorNotice, SectionTitle } from './ui'

const number = (n) => new Intl.NumberFormat('en-GB').format(n)

/**
 * How much the AI is used and how much of its input DeepSeek served from its context cache (cheaper and
 * faster). The cache only reuses text that is identical at the start of the request, so the prompt keeps
 * everything that is the same for every complaint first and the complaint itself last.
 */
export default function AiUsageCard() {
  const usage = useApi('/genai/usage')
  const u = usage.data
  return (
    <Card className="flex flex-col gap-3 p-6 xl:col-span-2">
      <SectionTitle>AI usage and savings</SectionTitle>
      <ErrorNotice message={usage.error} />
      {u && u.total.calls === 0 && <p className="m-0 text-[15px] text-muted">No complaints have been analysed yet.</p>}
      {u && u.total.calls > 0 && (
        <>
          <p className="m-0 text-[15px] leading-relaxed">
            <strong>{u.total.cached_percent}%</strong> of everything sent to the AI was served from DeepSeek’s cache ({number(u.total.cached_tokens)} of {number(u.total.input_tokens)} input tokens, across {number(u.total.calls)} calls). Cached input is billed at a lower price and answers sooner.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-[14px]">
              <thead>
                <tr className="text-left text-[13px] text-muted">
                  {['Instructions', 'Calls', 'From cache', 'Input tokens', 'Answer tokens', 'Average time'].map((h) => (
                    <th key={h} scope="col" className="border-b border-line-soft px-2 py-2 font-semibold first:pl-0">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {u.by_version.map((r) => (
                  <tr key={r.prompt_version}>
                    <td className="border-b border-sand-2 py-2 pr-2 font-semibold">Version {r.prompt_version}</td>
                    <td className="border-b border-sand-2 px-2 py-2">
                      {number(r.calls)}
                      {r.failed > 0 && <span className="text-rust"> ({r.failed} failed)</span>}
                    </td>
                    <td className="border-b border-sand-2 px-2 py-2 font-semibold">{r.cached_percent}%</td>
                    <td className="border-b border-sand-2 px-2 py-2">{number(r.input_tokens)}</td>
                    <td className="border-b border-sand-2 px-2 py-2">{number(r.output_tokens)}</td>
                    <td className="border-b border-sand-2 px-2 py-2">{r.average_seconds} s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  )
}
