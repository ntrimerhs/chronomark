import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { FileText, FileUp, Loader2, Presentation, ScanText, Trash2, X } from 'lucide-react'
import { API_BASE_URL } from '../config'
import DocumentViewer from './documents/DocumentViewer.jsx'
import DocumentChat from './documents/DocumentChat.jsx'
import '../styles/proxeiro.css'
import '../styles/uploadTheme.css'
import '../styles/documentsTheme.css'

/* Documents page.

   Upload a PDF, a slide deck or a Word file, then read it beside a chat that
   answers with page citations. The pipeline lives in the backend: parse ->
   chunk -> embed -> index, exactly like a video's transcript. */

const ACCEPT = '.pdf,.pptx,.docx'
const KINDS = {
  pdf: { label: 'PDF', icon: FileText },
  pptx: { label: 'PowerPoint', icon: Presentation },
  docx: { label: 'Word', icon: ScanText },
}

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
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
  const [documents, setDocuments] = useState([])
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

  const loadDocuments = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/documents`, { timeout: 20000 })
      setDocuments(data.documents || [])
    } catch (loadError) {
      console.error('[Docs] list failed', loadError)
    }
  }, [])

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

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

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
              const status = await axios.get(`${API_BASE_URL}/upload-status/${jobId}`, { timeout: 20000 })
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
              // A single dropped poll is not a failure; keep trying.
              console.error('[Docs] status poll failed', pollError)
            }
          }, 2000)
        })

        setProgress(100)
        await openDocument(data.doc_id)
        await loadDocuments()
      } catch (uploadError) {
        setError(
          uploadError?.response?.data?.detail || uploadError?.message || 'Upload failed.',
        )
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
    [loadDocuments, openDocument],
  )

  const handleDelete = useCallback(
    async (docId) => {
      try {
        await axios.delete(`${API_BASE_URL}/api/document/${docId}`, { timeout: 30000 })
        if (current?.doc_id === docId) {
          setCurrent(null)
        }
        await loadDocuments()
      } catch (deleteError) {
        setError(deleteError?.response?.data?.detail || 'Could not delete this document.')
      }
    },
    [current, loadDocuments],
  )

  const jumpToPage = useCallback((page) => {
    setPageHint(page)
    viewerRef.current?.scrollToPage(page)
  }, [])

  const idle = !current && !uploading

  return (
    <main className="upload-shell docs-page">
      <header className="upload-hero">
        <span className="upload-eyebrow">02 Documents</span>
        <h1>
          Add a document. <em>Ask it anything.</em>
        </h1>
        <p className="upload-subtitle">
          PDF, PowerPoint and Word. The pipeline reads every page, indexes the
          text, and answers with the page the answer came from, so a handout
          behaves like a lecture recording you can question.
        </p>
      </header>

      {documents.length > 0 ? (
        <div className="docs-library">
          <span className="docs-library-label">Library</span>
          <div className="docs-library-row">
            {documents.map((item) => {
              const kind = KINDS[item.kind] || KINDS.pdf
              const Icon = kind.icon
              return (
                <div
                  key={item.doc_id}
                  className={`docs-card-chip${current?.doc_id === item.doc_id ? ' is-active' : ''}`}
                >
                  <button type="button" onClick={() => openDocument(item.doc_id)}>
                    <Icon size={13} />
                    <strong>{item.file_name}</strong>
                    <span>
                      {kind.label} · {item.page_count} pages
                    </span>
                  </button>
                  <button
                    type="button"
                    className="docs-chip-delete"
                    onClick={() => handleDelete(item.doc_id)}
                    aria-label={`Delete ${item.file_name}`}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}

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
                    PDF, PowerPoint or Word, up to 40 MB. Scanned PDFs are read with
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
        <section className="docs-workspace">
          <div className="docs-viewer-card">
            <header className="docs-viewer-head">
              <span className="docs-viewer-name">
                {(() => {
                  const kind = KINDS[current.kind] || KINDS.pdf
                  const Icon = kind.icon
                  return <Icon size={13} />
                })()}
                {current.file_name}
              </span>
              <span className="docs-viewer-meta">
                {current.page_count} pages
                <button type="button" onClick={() => setCurrent(null)} aria-label="Close document">
                  <X size={13} />
                </button>
              </span>
            </header>
            <DocumentViewer document={current} pageHint={pageHint} viewerRef={viewerRef} />
          </div>

          <DocumentChat document={current} onJumpToPage={jumpToPage} />
        </section>
      ) : null}

      {error ? <p className="upload-error docs-error">{error}</p> : null}
    </main>
  )
}
