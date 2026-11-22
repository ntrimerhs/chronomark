import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { FileText, FileUp, Loader2, Presentation, ScanText, X } from 'lucide-react'
import { API_BASE_URL } from '../config'
import DocumentViewer from './documents/DocumentViewer.jsx'
import DocumentChat from './documents/DocumentChat.jsx'
import '../styles/proxeiro.css'
import '../styles/uploadTheme.css'
import '../styles/documentsTheme.css'

/* Documents page.

   One document at a time, exactly like the video page: the pages on the left,
   the same chat on the right. There is no library -- opening the page is the
   upload, and the chat always belongs to the document in view. */

const ACCEPT = '.pdf,.pptx,.docx'
const KIND_META = {
  pdf: { label: 'PDF', icon: FileText },
  pptx: { label: 'PowerPoint', icon: Presentation },
  docx: { label: 'Word', icon: ScanText },
}

function statusLabel(stage) {
  switch (stage) {
    case 'queued':
      return 'Preparing'
    case 'parsing':
      return 'Reading'
    case 'chunking':
      return 'Splitting'
    case 'embedding':
      return 'Indexing'
    case 'finalizing':
      return 'Finishing'
    default:
      return 'Working'
  }
}

export default function Documents() {
  const [current, setCurrent] = useState(null)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [pageHint, setPageHint] = useState(null)
  const [dragging, setDragging] = useState(false)

  const viewerRef = useRef(null)
  const inputRef = useRef(null)
  const pollRef = useRef(null)

  const openDocument = useCallback(async (docId) => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/document/${docId}`, { timeout: 30000 })
      setCurrent({
        doc_id: data.doc_id,
        file_name: data.file_name,
        kind: data.kind,
        page_count: data.page_count,
        file_url: `${API_BASE_URL}${data.file_url}`,
        pages: data.pages || [],
      })
      setPageHint(null)
      setError('')
    } catch (openError) {
      setError(openError?.response?.data?.detail || 'Could not open this document.')
    }
  }, [])

  // Deep link: /documents?doc=<doc_id> opens that document straight away, which
  // is also how a link to a specific handout works.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get('doc')
    if (requested) openDocument(requested)
  }, [openDocument])

  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current)
  }, [])

  const handleFile = useCallback(
    async (file) => {
      if (!file) return
      const suffix = `.${file.name.split('.').pop()?.toLowerCase() || ''}`
      if (!ACCEPT.split(',').includes(suffix)) {
        setError('Only PDF, PPTX and DOCX files are supported.')
        return
      }

      setError('')
      setUploading(true)
      setProgress(0)
      setStage('Uploading')

      try {
        const form = new FormData()
        form.append('file_upload', file, file.name)

        const { data } = await axios.post(`${API_BASE_URL}/api/upload-document`, form, {
          timeout: 300000,
          onUploadProgress: (event) => {
            if (!event.total) return
            setProgress(Math.min(15, Math.round((event.loaded / event.total) * 15)))
          },
        })

        setStage('parsing')
        const jobId = data.job_id

        await new Promise((resolve, reject) => {
          pollRef.current = window.setInterval(async () => {
            try {
              const status = await axios.get(`${API_BASE_URL}/upload-status/${jobId}`, {
                timeout: 20000,
              })
              const job = status.data
              if (job.progress) setProgress(Math.max(15, Math.min(99, job.progress)))
              if (job.stage) setStage(job.stage)

              if (job.status === 'completed') {
                window.clearInterval(pollRef.current)
                pollRef.current = null
                resolve()
              } else if (job.status === 'failed') {
                window.clearInterval(pollRef.current)
                pollRef.current = null
                reject(new Error(job.error || 'Processing failed'))
              }
            } catch (pollError) {
              // One dropped poll is not a failure; keep trying.
              console.error('[Docs] status poll failed', pollError)
            }
          }, 2000)
        })

        setProgress(100)
        await openDocument(data.doc_id)
      } catch (uploadError) {
        setError(uploadError?.response?.data?.detail || uploadError?.message || 'Upload failed.')
      } finally {
        if (pollRef.current) {
          window.clearInterval(pollRef.current)
          pollRef.current = null
        }
        setUploading(false)
        setStage('')
        setProgress(0)
        if (inputRef.current) inputRef.current.value = ''
      }
    },
    [openDocument],
  )

  const jumpToPage = useCallback((page) => {
    setPageHint(page)
    viewerRef.current?.scrollToPage(page)
  }, [])

  const idle = !current && !uploading
  const kindMeta = KIND_META[current?.kind] || KIND_META.pdf
  const KindIcon = kindMeta.icon

  return (
    <main className="upload-shell docs-page">
      <header className="upload-hero">
        <span className="upload-eyebrow">02 Documents</span>
        <h1>
          Add a document. <em>Ask it anything.</em>
        </h1>
        <p className="upload-subtitle">
          PDF, PowerPoint and Word. Every page is read and indexed, and answers
          point at the page they came from, the same way the video answers point
          at a moment.
        </p>
      </header>

      {idle ? (
        <section className="upload-grid">
          <div className="upload-center-card">
            <div className="upload-dropzone">
              <div
                className={`docs-drop${dragging ? ' is-dragging' : ''}`}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  handleFile(event.dataTransfer.files?.[0])
                }}
              >
                <button
                  type="button"
                  className="upload-dropzone-button"
                  onClick={() => inputRef.current?.click()}
                >
                  <span className="upload-dropzone-icon" aria-hidden="true">
                    <FileUp size={30} strokeWidth={1.4} />
                  </span>
                  <span className="upload-dropzone-title">Drop a document or click</span>
                  <span className="upload-dropzone-copy">
                    PDF, PowerPoint or Word, up to 40 MB. Scanned pages are read with
                    OCR, slide speaker notes are indexed too.
                  </span>
                </button>
                <input
                  ref={inputRef}
                  type="file"
                  accept={ACCEPT}
                  hidden
                  onChange={(event) => handleFile(event.target.files?.[0])}
                />
              </div>

              <div className="upload-spec" aria-hidden="true">
                <p className="upload-spec-row">
                  <span>Parse</span>
                  <i />
                  <strong>Pdf / Pptx / Docx</strong>
                </p>
                <p className="upload-spec-row">
                  <span>Index</span>
                  <i />
                  <strong>Qdrant - Pages</strong>
                </p>
                <p className="upload-spec-row">
                  <span>Answer</span>
                  <i />
                  <strong>Deepseek - Cited</strong>
                </p>
                <p className="upload-spec-note">Status / waiting for a document</p>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {uploading ? (
        <section className="upload-grid">
          <div className="upload-center-card">
            <div className="upload-dropzone docs-progress-card">
              <Loader2 size={26} className="docs-spin docs-progress-icon" />
              <p className="docs-progress-stage">{statusLabel(stage)}</p>
              <div className="upload-progress-block">
                <progress value={progress} max={100} />
                <div className="upload-progress-labels">
                  <span>{stage}</span>
                  <span className="upload-progress-value">{progress}%</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {current ? (
        <section className="upload-grid upload-grid-loaded docs-workspace">
          <div className="upload-center-card upload-center-card-doc">
            <header className="upload-loaded-header docs-viewer-head">
              <span className="upload-video-title docs-viewer-name">
                <KindIcon size={13} />
                {current.file_name}
              </span>
              <span className="upload-secondary-action docs-viewer-meta">
                {kindMeta.label} · {current.page_count} pages
                <button
                  type="button"
                  onClick={() => setCurrent(null)}
                  aria-label="Close document"
                >
                  <X size={13} />
                </button>
              </span>
            </header>
            <DocumentViewer document={current} pageHint={pageHint} viewerRef={viewerRef} />
          </div>

          <div className="chat-panel docs-chat-panel">
            <DocumentChat document={current} onJumpToPage={jumpToPage} />
          </div>
        </section>
      ) : null}

      {error ? <p className="upload-error docs-error">{error}</p> : null}
    </main>
  )
}
