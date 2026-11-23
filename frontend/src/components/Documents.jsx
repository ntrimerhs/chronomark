import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { FileUp, Loader2, PanelLeft } from 'lucide-react'
import { API_BASE_URL } from '../config'
import WorkspaceSidebar from './documents/WorkspaceSidebar.jsx'
import WorkspaceViewer from './documents/WorkspaceViewer.jsx'
import WorkspaceChat from './documents/WorkspaceChat.jsx'
import '../styles/documentsReference.css'
import '../styles/documentsLanding.css'

/* Documents workspace: conversations on the left, the pages in the middle, the
   chat on the right. Every control acts on real data: the PDF comes from R2, the
   conversations from the API, the citations from the model's answer.

   One workspace per document. There is no top bar: the file name moved into the
   viewer's head, and "New chat" returns to the landing screen, because a new
   conversation means a new document to read. */

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

  // A new conversation on the document already open. Used silently the first
  // time a question is asked in a workspace that has no conversation yet.
  const createChat = useCallback(async () => {
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

  // A new chat means a new document, so it starts at the landing screen and
  // nothing of the old workspace survives.
  const startNewWorkspace = useCallback(() => {
    setChatId(null)
    setChats([])
    setPage(1)
    setZoom(100)
    setError('')
    setMobilePane('document')
    setCurrent(null)
  }, [])

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

  // Drag the seam: the ratio lives in --left, which the layout reads.
  //
  // The drag used to die the moment the cursor crossed the PDF. An iframe is a
  // document of its own, so the moves and the release went to the PDF viewer
  // instead of this window: the seam froze under the mouse while the cursor kept
  // travelling, and the next mouse move over the chat carried on resizing. The
  // handle captures the pointer (so events keep coming here whatever they are
  // over), the frame ignores the pointer for the duration (see the .is-resizing
  // rule), and a release outside the window -- pointercancel, blur, or a move
  // with no buttons down -- ends the drag instead of leaving it armed.
  useEffect(() => {
    if (!dragging) return undefined

    const previousCursor = document.body.style.cursor
    const previousSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    function move(event) {
      if (!workspaceRef.current) return
      if (event.pointerType === 'mouse' && event.buttons === 0) {
        setDragging(false)
        return
      }
      const rect = workspaceRef.current.getBoundingClientRect()
      if (!rect.width) return
      const percent = ((event.clientX - rect.left) / rect.width) * 100
      setSplit(Math.min(74, Math.max(32, Math.round(percent))))
    }
    function stop() {
      setDragging(false)
    }

    window.addEventListener('pointermove', move, true)
    window.addEventListener('pointerup', stop, true)
    window.addEventListener('pointercancel', stop, true)
    window.addEventListener('blur', stop)

    return () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousSelect
      window.removeEventListener('pointermove', move, true)
      window.removeEventListener('pointerup', stop, true)
      window.removeEventListener('pointercancel', stop, true)
      window.removeEventListener('blur', stop)
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
            startNewWorkspace()
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
          {/* Mobile only: one segmented control to move between the pages and
              the conversation. On a desktop both are on screen at once, and the
              top bar that used to hold this, the file name and the two buttons
              is gone -- the file name now sits in the viewer's head. */}
          <div className="workspace-rail">
            <button
              type="button"
              className="rail-history"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open conversation history"
            >
              <PanelLeft size={15} />
              Chats
            </button>
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
          </div>

          {/* The stylesheet's mobile rules key off `mobile-doc` / `mobile-chat`,
              so the pane name is mapped here -- `mobile-document` matched
              nothing and both panels stayed display:none on a phone. */}
          <section
            ref={workspaceRef}
            className={`workspace mobile-${mobilePane === 'document' ? 'doc' : 'chat'}${dragging ? ' is-resizing' : ''}`}
            style={{ '--left': `${split}%` }}
          >
            <WorkspaceViewer
              document={current}
              page={page}
              zoom={zoom}
              onPage={jumpToPage}
              onZoom={zoomBy}
            />

            <div
              className={`resize${dragging ? ' drag' : ''}`}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize document and chat panels"
              onPointerDown={(event) => {
                if (event.button !== 0 && event.pointerType === 'mouse') return
                event.preventDefault()
                // Capture the pointer: without it the seam stops hearing moves
                // the moment the cursor crosses the PDF iframe, and the drag
                // never ends -- the cursor comes back over the chat still
                // resizing the layout. Captured events keep arriving here, and
                // the frame is made transparent to the pointer below.
                try {
                  event.currentTarget.setPointerCapture(event.pointerId)
                } catch {
                  /* older browsers: the iframe lock and the window listeners
                     below still end the drag */
                }
                setDragging(true)
              }}
            />

            <WorkspaceChat
              document={current}
              chatId={chatId}
              title={chats.find((chat) => chat.id === chatId)?.title}
              onCreateChat={createChat}
              onNewChat={startNewWorkspace}
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
