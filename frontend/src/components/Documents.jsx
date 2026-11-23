import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { FileUp, Loader2, MessageSquarePlus, Upload, X } from 'lucide-react'
import { API_BASE_URL } from '../config'
import WorkspaceSidebar from './documents/WorkspaceSidebar.jsx'
import WorkspaceViewer from './documents/WorkspaceViewer.jsx'
import WorkspaceChat from './documents/WorkspaceChat.jsx'
import '../styles/documentsReference.css'
import '../styles/documentsLanding.css'

/* Documents workspace, built to the design reference: conversations on the left,
   the pages in the middle, the chat on the right, all inside the reference's own
   layout and spacing. Every control acts on real data: the PDF comes from R2, the
   conversations from the API, the citations from the model's answer. */

const ACCEPT = '.pdf,.pptx,.docx'
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
  const [showThumbs, setShowThumbs] = useState(true)
  const [mobilePane, setMobilePane] = useState('document')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() =>
    readStored('cm.docs.sidebarCollapsed', false),
  )
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [split, setSplit] = useState(() => Number(readStored('cm.docs.split', 58)) || 58)
  const [dragging, setDragging] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  const inputRef = useRef(null)
  const pollRef = useRef(null)
  const workspaceRef = useRef(null)

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

  const jumpToPage = useCallback(
    (nextPage) => {
      const total = current?.page_count || 1
      setPage(Math.min(Math.max(1, Number(nextPage) || 1), total))
      setMobilePane('document')
    },
    [current],
  )

  function zoomBy(direction) {
    const index = ZOOM_STEPS.indexOf(zoom)
    const next = ZOOM_STEPS[
      Math.min(ZOOM_STEPS.length - 1, Math.max(0, (index < 0 ? 2 : index) + direction))
    ]
    setZoom(next)
  }

  // Drag the seam: the ratio lives in --left, which the reference layout reads.
  useEffect(() => {
    function move(event) {
      if (!dragging || !workspaceRef.current) return
      const rect = workspaceRef.current.getBoundingClientRect()
      if (!rect.width) return
      const percent = ((event.clientX - rect.left) / rect.width) * 100
      setSplit(Math.min(74, Math.max(32, Math.round(percent))))
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

  if (!current) {
    return (
      <div className="docs-landing">
        <header className="docs-landing-head">
          <span className="docs-breadcrumb">
            Your workspace <i>/</i> <strong>Documents</strong>
          </span>
          <h1>
            Add a document. <em>Ask it anything.</em>
          </h1>
          <p>
            PDF, PowerPoint and Word. Every page is read and indexed, figures are read too, and
            each answer points at the page it came from.
          </p>
        </header>

        <section
          className={`docs-landing-card${dragOver ? ' is-dragging' : ''}`}
          onDragOver={(event) => {
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragOver(false)
            handleFile(event.dataTransfer.files?.[0])
          }}
        >
          {uploading ? (
            <div className="docs-uploading">
              <Loader2 size={26} className="docs-spin" />
              <p>{statusLabel(stage)}</p>
              <div className="docs-bar">
                <span style={{ width: `${progress}%` }} />
              </div>
              <small>{progress}%</small>
            </div>
          ) : (
            <button type="button" className="docs-drop" onClick={() => inputRef.current?.click()}>
              <FileUp size={30} strokeWidth={1.4} />
              <strong>Drop a document or click</strong>
              <span>
                PDF, PowerPoint or Word, up to 40 MB. Scanned pages are read with OCR, and slide
                speaker notes are indexed too.
              </span>
            </button>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(event) => handleFile(event.target.files?.[0])}
          />
        </section>

        {error ? <p className="docs-landing-error">{error}</p> : null}
      </div>
    )
  }

  return (
    <div className="docs-app dark">
      <div className="app-layout">
        <WorkspaceSidebar
          chats={chats}
          activeChatId={chatId}
          document={current}
          collapsed={sidebarCollapsed}
          open={sidebarOpen}
          onToggle={() => setSidebarCollapsed((value) => !value)}
          onNewChat={() => {
            newChat()
            setSidebarOpen(false)
          }}
          onSelect={(id) => {
            setChatId(id)
            setMobilePane('chat')
            setSidebarOpen(false)
          }}
          onDelete={deleteChat}
          onClose={() => setSidebarOpen(false)}
        />

        <main className="app-body">
          <section className="workspace-info">
            <div className="file-intro">
              <button
                type="button"
                className="icon-btn topbar-menu"
                onClick={() => setSidebarOpen(true)}
                aria-label="Open conversation history"
              >
                <MessageSquarePlus size={16} />
              </button>
              <div className="file-icon">
                <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M6 2.5h8l5 5V21H6a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2Z" />
                  <path d="M14 2.5v5h5M8 13h8M8 17h6" />
                </svg>
              </div>
              <div className="doc-meta">
                <div className="eyebrow">Your workspace / Documents</div>
                <h1 title={current.file_name}>{current.file_name}</h1>
                <div className="fileline">
                  <span>{(current.kind || 'pdf').toUpperCase()} document</span>
                  <span className="sep-dot" />
                  <span>{current.page_count} pages</span>
                  <span className="sep-dot" />
                  <span className="saved">
                    <i />
                    Ready to explore
                  </span>
                </div>
              </div>
            </div>

            <div className="doc-badge">
              <div className="mobile-tabs">
                <button
                  type="button"
                  className={mobilePane === 'document' ? 'active' : ''}
                  onClick={() => setMobilePane('document')}
                >
                  Document
                </button>
                <button
                  type="button"
                  className={mobilePane === 'chat' ? 'active' : ''}
                  onClick={() => setMobilePane('chat')}
                >
                  Chat
                </button>
              </div>
              <button type="button" className="outline-btn" onClick={newChat}>
                <MessageSquarePlus size={15} /> New chat
              </button>
              <button type="button" className="primary-btn" onClick={() => setCurrent(null)}>
                <Upload size={16} /> Open a PDF
              </button>
              <button
                type="button"
                className="outline-btn"
                onClick={() => setCurrent(null)}
                aria-label="Close document"
                style={{ display: 'none' }}
              >
                <X size={15} />
              </button>
            </div>
          </section>

          <section
            ref={workspaceRef}
            className={`workspace mobile-${mobilePane}`}
            style={{ '--left': `${split}%` }}
          >
            <WorkspaceViewer
              document={current}
              page={page}
              zoom={zoom}
              onPage={jumpToPage}
              onZoom={zoomBy}
              showThumbs={showThumbs}
              onToggleThumbs={() => setShowThumbs((value) => !value)}
            />

            <div
              className={`resize${dragging ? ' drag' : ''}`}
              role="separator"
              aria-label="Resize document and chat panels"
              onPointerDown={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
            />

            <WorkspaceChat
              document={current}
              chatId={chatId}
              title={chats.find((chat) => chat.id === chatId)?.title}
              onCreateChat={newChat}
              onChatChanged={() => loadChats(current.doc_id)}
              onJumpToPage={jumpToPage}
            />
          </section>

          {error ? <p className="docs-workspace-error">{error}</p> : null}
        </main>
      </div>
    </div>
  )
}
