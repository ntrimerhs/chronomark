import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  FileUp,
  Loader2,
  Maximize2,
  MessageSquarePlus,
  Minimize2,
  Minus,
  Plus,
  Presentation,
  ScanText,
  X,
} from 'lucide-react'
import { API_BASE_URL } from '../config'
import DocumentViewer from './documents/DocumentViewer.jsx'
import DocumentChat from './documents/DocumentChat.jsx'
import DocumentsSidebar from './documents/DocumentsSidebar.jsx'
import '../styles/proxeiro.css'
import '../styles/uploadTheme.css'
import '../styles/documentsTheme.css'
import '../styles/documentsWorkspace.css'

/* Documents page.

   One document at a time, laid out like a study workspace rather than a form:
   a conversations sidebar on the left, the pages in the middle, the chat on the
   right, and a divider you can drag. Everything the page shows comes from the
   document you opened: its pages, its conversations, its citations. */

const ACCEPT = '.pdf,.pptx,.docx'
const KIND_META = {
  pdf: { label: 'PDF', icon: FileText },
  pptx: { label: 'PowerPoint', icon: Presentation },
  docx: { label: 'Word', icon: ScanText },
}
const ZOOM_STEPS = [75, 90, 100, 110, 125, 150, 175, 200]

function statusLabel(stage) {
  switch (stage) {
    case 'queued':
      return 'Preparing'
    case 'parsing':
      return 'Reading'
    case 'chunking':
      return 'Splitting'
    case 'reading_figures':
      return 'Reading figures'
    case 'embedding':
      return 'Indexing'
    case 'finalizing':
      return 'Finishing'
    default:
      return 'Working'
  }
}

function readStored(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key)
    return raw === null ? fallback : JSON.parse(raw)
  } catch {
    return fallback
  }
}

export default function Documents() {
  const [current, setCurrent] = useState(null)
  const [chats, setChats] = useState([])
  const [chatId, setChatId] = useState(null)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState('')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(100)
  const [viewerMode, setViewerMode] = useState('pdf')
  const [focusMode, setFocusMode] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [mobilePane, setMobilePane] = useState('document')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() =>
    readStored('cm.docs.sidebarCollapsed', true),
  )
  const [split, setSplit] = useState(() => Number(readStored('cm.docs.split', 58)) || 58)

  const viewerRef = useRef(null)
  const inputRef = useRef(null)
  const pollRef = useRef(null)
  const splitRef = useRef(null)

  // Preferences are UI state, so they live in the browser, not in the API.
  useEffect(() => {
    window.localStorage.setItem('cm.docs.sidebarCollapsed', JSON.stringify(sidebarCollapsed))
  }, [sidebarCollapsed])

  useEffect(() => {
    window.localStorage.setItem('cm.docs.split', JSON.stringify(split))
  }, [split])

  const loadChats = useCallback(async (docId) => {
    if (!docId) return []
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/document/${docId}/chats`, {
        timeout: 30000,
      })
      setChats(data.chats || [])
      return data.chats || []
    } catch (loadError) {
      console.error('[Chats] list failed', loadError)
      return []
    }
  }, [])

  const openDocument = useCallback(
    async (docId) => {
      try {
        const { data } = await axios.get(`${API_BASE_URL}/api/document/${docId}`, {
          timeout: 30000,
        })
        setCurrent({
          doc_id: data.doc_id,
          file_name: data.file_name,
          kind: data.kind,
          page_count: data.page_count,
          language: data.language,
          file_url: `${API_BASE_URL}${data.file_url}`,
          pages: data.pages || [],
        })
        setPage(1)
        setError('')

        const list = await loadChats(docId)
        setChatId(list.length ? list[0].id : null)
      } catch (openError) {
        setError(openError?.response?.data?.detail || 'Could not open this document.')
      }
    },
    [loadChats],
  )

  // Deep link: /documents?doc=<doc_id> opens that document straight away.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get('doc')
    if (requested) openDocument(requested)
  }, [openDocument])

  useEffect(
    () => () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    },
    [],
  )

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

  const newChat = useCallback(async () => {
    if (!current) return null
    try {
      const { data } = await axios.post(
        `${API_BASE_URL}/api/document/${current.doc_id}/chats`,
        { title: 'New chat' },
        { timeout: 30000 },
      )
      setChatId(data.id)
      setMobilePane('chat')
      await loadChats(current.doc_id)
      return data.id
    } catch (createError) {
      setError(createError?.response?.data?.detail || 'Could not start a new conversation.')
      return null
    }
  }, [current, loadChats])

  const deleteChat = useCallback(
    async (id) => {
      if (!current) return
      try {
        await axios.delete(`${API_BASE_URL}/api/document/${current.doc_id}/chats/${id}`, {
          timeout: 30000,
        })
        const remaining = await loadChats(current.doc_id)
        if (chatId === id) setChatId(remaining.length ? remaining[0].id : null)
      } catch (deleteError) {
        setError(deleteError?.response?.data?.detail || 'Could not delete the conversation.')
      }
    },
    [chatId, current, loadChats],
  )

  const jumpToPage = useCallback((nextPage) => {
    const total = current?.page_count || 1
    const clamped = Math.min(Math.max(1, Number(nextPage) || 1), total)
    setPage(clamped)
    setMobilePane('document')
    viewerRef.current?.scrollToPage(clamped)
  }, [current])

  // Dragging the divider: the ratio is kept in a ref during the move so the
  // pointer handler never reads stale state.
  useEffect(() => {
    function move(event) {
      if (!dragging || !splitRef.current) return
      const rect = splitRef.current.getBoundingClientRect()
      if (!rect.width) return
      const percent = ((event.clientX - rect.left) / rect.width) * 100
      setSplit(Math.min(75, Math.max(32, Math.round(percent))))
    }
    function stop() {
      setDragging(false)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
  }, [dragging])

  const idle = !current && !uploading
  const kindMeta = KIND_META[current?.kind] || KIND_META.pdf
  const KindIcon = kindMeta.icon

  function zoomBy(direction) {
    const index = ZOOM_STEPS.indexOf(zoom)
    const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, (index < 0 ? 2 : index) + direction))]
    setZoom(next)
  }

  if (idle || uploading) {
    return (
      <main className="docs-landing">
        <header className="docs-landing-head">
          <span className="docs-eyebrow">02 Documents</span>
          <h1>
            Add a document. <em>Ask it anything.</em>
          </h1>
          <p>
            PDF, PowerPoint and Word. Every page is read and indexed, figures are read too, and
            each answer points at the page it came from.
          </p>
        </header>

        <section className="docs-landing-card">
          {uploading ? (
            <div className="docs-progress-card">
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
          ) : (
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
                  PDF, PowerPoint or Word, up to 40 MB. Scanned pages are read with OCR, slide
                  speaker notes are indexed too.
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
          )}
        </section>

        {error ? <p className="docs-chat-error">{error}</p> : null}
      </main>
    )
  }

  return (
    <div
      className={`docs-app${sidebarCollapsed ? ' sidebar-collapsed' : ''}${sidebarOpen ? ' sidebar-open' : ''}`}
    >
      <DocumentsSidebar
        chats={chats}
        activeChatId={chatId}
        document={current}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((value) => !value)}
        onNewChat={newChat}
        onSelect={(id) => {
          setChatId(id)
          setMobilePane('chat')
          setSidebarOpen(false)
        }}
        onDelete={deleteChat}
      />

      <main className="docs-main">
        <div className="docs-workspace-info">
          <div className="docs-file-intro">
            <span className="docs-file-icon">
              <KindIcon size={18} />
            </span>
            <div className="docs-file-meta">
              <span className="docs-breadcrumb">
                Your workspace <i>/</i> <strong>Documents</strong>
              </span>
              <h1 title={current.file_name}>{current.file_name}</h1>
              <div className="docs-file-line">
                <span>{kindMeta.label}</span>
                <span className="docs-dot" />
                <span>{current.page_count} pages</span>
                <span className="docs-dot" />
                <span className="docs-saved">
                  <i /> Indexed
                </span>
              </div>
            </div>
          </div>

          <div className="docs-head-actions">
            <button
              type="button"
              className="docs-outline-btn docs-only-mobile"
              onClick={() => setSidebarOpen((value) => !value)}
            >
              <MessageSquarePlus size={14} />
              Chats
            </button>
            <div className="docs-mobile-tabs">
              <button
                type="button"
                className={mobilePane === 'document' ? 'is-active' : ''}
                onClick={() => setMobilePane('document')}
              >
                Pages
              </button>
              <button
                type="button"
                className={mobilePane === 'chat' ? 'is-active' : ''}
                onClick={() => setMobilePane('chat')}
              >
                Chat
              </button>
            </div>
            <button type="button" className="docs-outline-btn" onClick={newChat}>
              <MessageSquarePlus size={14} />
              New chat
            </button>
            <button
              type="button"
              className="docs-outline-btn"
              onClick={() => setFocusMode((value) => !value)}
            >
              {focusMode ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              {focusMode ? 'Show chat' : 'Wide'}
            </button>
            <button type="button" className="docs-primary-btn" onClick={() => setCurrent(null)}>
              <X size={14} />
              Close
            </button>
          </div>
        </div>

        <div
          ref={splitRef}
          className={`docs-split${dragging ? ' is-dragging' : ''}${focusMode ? ' is-focus' : ''} mobile-${mobilePane}`}
          style={{ '--split': `${split}%` }}
        >
          <section className="docs-panel docs-document-panel">
            <header className="docs-panel-head">
              <span className="docs-panel-title">Pages</span>
              <div className="docs-toolset">
                <button
                  type="button"
                  className="docs-icon-btn"
                  onClick={() => jumpToPage(page - 1)}
                  disabled={page <= 1}
                  aria-label="Previous page"
                >
                  <ChevronLeft size={15} />
                </button>
                <span className="docs-pagecount">
                  <input
                    className="docs-pagefield"
                    value={page}
                    onChange={(event) => {
                      const value = Number(event.target.value.replace(/\D/g, ''))
                      if (value) jumpToPage(value)
                    }}
                    aria-label="Page"
                  />
                  <em>/ {current.page_count}</em>
                </span>
                <button
                  type="button"
                  className="docs-icon-btn"
                  onClick={() => jumpToPage(page + 1)}
                  disabled={page >= current.page_count}
                  aria-label="Next page"
                >
                  <ChevronRight size={15} />
                </button>

                <span className="docs-divider" />

                <button
                  type="button"
                  className="docs-icon-btn"
                  onClick={() => zoomBy(-1)}
                  aria-label="Zoom out"
                >
                  <Minus size={14} />
                </button>
                <span className="docs-zoom">{zoom}%</span>
                <button
                  type="button"
                  className="docs-icon-btn"
                  onClick={() => zoomBy(1)}
                  aria-label="Zoom in"
                >
                  <Plus size={14} />
                </button>

                <span className="docs-divider" />

                <button
                  type="button"
                  className={`docs-icon-btn${viewerMode === 'text' ? ' is-on' : ''}`}
                  onClick={() => setViewerMode((value) => (value === 'pdf' ? 'text' : 'pdf'))}
                  title={viewerMode === 'pdf' ? 'Show the extracted text' : 'Show the PDF pages'}
                >
                  {viewerMode === 'pdf' ? <ScanText size={14} /> : <FileText size={14} />}
                </button>
              </div>
            </header>
            <DocumentViewer
              document={current}
              page={page}
              zoom={zoom}
              mode={viewerMode}
              viewerRef={viewerRef}
            />
            <footer className="docs-viewer-foot">
              <span>{current.file_name}</span>
              <span>
                {page} / {current.page_count}
              </span>
            </footer>
          </section>

          <div
            className="docs-resize"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the pages and chat"
            onPointerDown={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
          />

          <section className="docs-panel docs-chat-panel-outer">
            <header className="docs-panel-head">
              <span className="docs-chat-heading">
                <span className="docs-chat-icon">
                  <FileText size={15} />
                </span>
                <span className="docs-chat-info">
                  <strong>Ask the document</strong>
                  <small>
                    <i /> {chats.find((chat) => chat.id === chatId)?.title || 'New conversation'}
                  </small>
                </span>
              </span>
              <div className="docs-toolset">
                <button type="button" className="docs-outline-btn" onClick={newChat}>
                  <MessageSquarePlus size={13} />
                  New
                </button>
              </div>
            </header>

            <DocumentChat
              document={current}
              chatId={chatId}
              onCreateChat={newChat}
              onChatChanged={() => loadChats(current.doc_id)}
              onJumpToPage={jumpToPage}
            />
          </section>
        </div>

        {error ? <p className="docs-chat-error">{error}</p> : null}
      </main>
    </div>
  )
}
