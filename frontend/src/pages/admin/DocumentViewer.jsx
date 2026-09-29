import { Badge, Button, Card, ErrorNotice, Loading, SectionTitle } from '../../components/ui'
import { formatDate } from '../../lib/format'
import { useApi } from '../../lib/useApi'

const STATUS = { active: 'In use', previous: 'Previous version', superseded: 'Replaced', draft: 'Draft' }
const STATUS_TONE = { active: 'green', draft: 'sun', previous: 'sand', superseded: 'sand' }

/** One policy document: its versions and the sections the assistant quotes from. */
export default function DocumentViewer({ doc, onPick, onClose }) {
  const history = useApi(`/kb/documents/history/${doc.doc_id}`)
  const sections = useApi(`/kb/documents/${doc.id}/chunks`)
  const size = doc.file_size ? `${Math.max(1, Math.round(doc.file_size / 1024))} KB` : ''

  return (
    <Card className="flex min-w-0 flex-col gap-4 p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <SectionTitle>{doc.title.replace(/^Lumora Home Technologies\s*[-–]\s*/, '')}</SectionTitle>
          <p className="m-0 text-[14px] text-muted">
            {[doc.doc_id, `version ${doc.version}`, doc.original_filename, doc.page_count && `${doc.page_count} pages`, size].filter(Boolean).join(' · ')}
          </p>
          <p className="m-0 text-[14px] text-muted">
            In effect from {formatDate(doc.effective_date)}
            {doc.expiry_date && ` until ${formatDate(doc.expiry_date)}`} · added {formatDate(doc.uploaded_at)}
            {doc.uploaded_by && ` by ${doc.uploaded_by}`}
          </p>
        </div>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="m-0 text-[15px] font-semibold">Versions</h3>
        <ErrorNotice message={history.error} />
        <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
          {(history.data || []).map((v) => (
            <li key={v.id}>
              <button
                type="button"
                onClick={() => onPick(v)}
                aria-current={v.id === doc.id}
                className={`flex w-full flex-wrap items-center gap-2 rounded-xl border-[1.5px] px-3 py-2 text-left text-[15px] ${v.id === doc.id ? 'border-forest bg-mint' : 'border-line bg-white hover:bg-cream'}`}
              >
                <span className="font-semibold">Version {v.version}</span>
                <Badge tone={STATUS_TONE[v.status]}>{STATUS[v.status] || v.status}</Badge>
                <span className="text-[14px] text-muted">from {formatDate(v.effective_date)}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="m-0 text-[15px] font-semibold">Sections {sections.data && <span className="font-normal text-muted">({sections.data.length})</span>}</h3>
        <ErrorNotice message={sections.error} onRetry={sections.reload} />
        {sections.loading && <Loading />}
        <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
          {(sections.data || []).map((s) => (
            <details key={s.chunk_id} className="rounded-xl bg-sand px-4 py-2.5">
              <summary className="cursor-pointer text-[15px] font-semibold">
                {s.section && `${s.section} `}
                {s.heading || 'Untitled section'}
                {s.page && <span className="font-normal text-muted"> · page {s.page}</span>}
              </summary>
              <p className="m-0 mt-2 text-[15px] leading-relaxed whitespace-pre-line">{s.text}</p>
            </details>
          ))}
        </div>
      </div>
    </Card>
  )
}
