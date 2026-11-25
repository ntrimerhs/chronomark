import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { FileText, FileUp, Loader2, PanelLeft, Plus, Video } from 'lucide-react'
import { API_BASE_URL } from '../config'
import AppSidebar from './common/AppSidebar.jsx'
import WorkspaceViewer from './documents/WorkspaceViewer.jsx'
import WorkspaceChat from './documents/WorkspaceChat.jsx'
import useLibrary from '../hooks/useLibrary.js'
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
    case 'summarising':
      // The study summary is generated before the document is announced as
      // ready, so the summary button never has to wait for it.
      return 'Preparing the summary'
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
  // One library for the whole page: every document and every recording, so the
  // column says the same thing here as it does in the other two workspaces.
  const library = useLibrary()
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
          // null once the upload has aged out of the bucket (three hours);
          // the viewer explains it instead of loading a broken frame.
          file_url: data.file_url ? `${API_BASE_URL}${data.file_url}` : '',
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

        // The same file submitted twice comes back as the document it already
        // became: nothing to queue, so nothing to poll.
        if (data.duplicate) {
          setProgress(100)
          await openDocument(data.doc_id)
          await library.refresh()
          return
        }

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
      <div className="dl">
        <div className="dl-sheet">
          <header className="dl-head">
            <h1 className="dl-title">Add a document.</h1>
            <p className="dl-answer">Ask it anything.</p>
            <p className="dl-copy">
              PDF, PowerPoint and Word. Every page is read and indexed, figures are read too, and
              each answer points at the page it came from.
            </p>
          </header>

          <section
            className={`dl-desk${dragOver ? ' is-dragging' : ''}${uploading ? ' is-working' : ''}`}
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
            <span className="dl-bracket is-tl" aria-hidden="true" />
            <span className="dl-bracket is-tr" aria-hidden="true" />
            <span className="dl-bracket is-bl" aria-hidden="true" />
            <span className="dl-bracket is-br" aria-hidden="true" />

            {uploading ? (
              <div className="dl-working">
                <span className="dl-working-stage">
                  <Loader2 size={16} className="docs-spin" />
                  {statusLabel(stage)}
                </span>
                <div className="dl-track">
                  <span style={{ width: `${progress}%` }} />
                </div>
                <span className="dl-working-value">{progress}%</span>
              </div>
            ) : (
              <button type="button" className="dl-drop" onClick={() => inputRef.current?.click()}>
                <span className="dl-icon-wrap">
                  <span className="dl-icon-glow" aria-hidden="true" />
                  <span className="dl-icon">
                    <FileUp size={30} strokeWidth={1.7} />
                  </span>
                </span>

                <span className="dl-drop-title">Drop a document or click</span>
                <span className="dl-drop-copy">
                  Every page is read and indexed, figures too. Scanned pages go through OCR, and
                  slide speaker notes are indexed as well.
                </span>

                <span className="dl-pill">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                    <path
                      d="M6 3.75h8.25L18.75 8.25V20.25H6z M14.25 3.75v4.5h4.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="1.6"
                    />
                  </svg>
                  PDF · PPTX · DOCX (UP TO 40 MB)
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

          {error ? <p className="dl-error">{error}</p> : null}
        </div>
      </div>
    )
  }

  return (
    <div className="docs-app dark">
      <div className="app-layout">
        <AppSidebar
          items={[
            ...library.documents.map((doc) => ({
              id: doc.doc_id,
              title: doc.file_name || 'Untitled document',
              updated_at: doc.created_at,
              group: 'Library',
              icon: FileText,
              active: current?.doc_id === doc.doc_id,
              deletable: false,
            })),
            ...library.videos.map((video) => ({
              id: video.video_id,
              title: video.title || 'Recording',
              updated_at: video.created_at,
              group: 'Library',
              icon: Video,
              deletable: false,
            })),
            ...chats.map((chat) => ({
              id: chat.id,
              title: chat.title,
              updated_at: chat.updated_at,
            })),
          ]}
          activeId={chatId}
          collapsed={sidebarCollapsed}
          open={sidebarOpen}
          onToggle={() => setSidebarCollapsed((value) => !value)}
          onClose={() => setSidebarOpen(false)}
          actions={[
            {
              key: 'new',
              icon: Plus,
              label: 'New chat',
              title: 'New chat (upload another document)',
              primary: true,
              onClick: () => {
                startNewWorkspace()
                setSidebarOpen(false)
              },
            },
          ]}
          search={{ placeholder: 'Search conversation history', label: 'Search chats' }}
          emptyText="Nothing yet. Upload a file to start one."
          onSelectItem={(id) => {
            const key = String(id || '')
            if (key.startsWith('doc_')) {
              openDocument(key)
              setSidebarOpen(false)
              return
            }
            // A recording has its own workspace; the library is the way to it.
            if (!key.startsWith('chat_')) {
              window.location.assign('/workspaces')
              return
            }
            setChatId(key)
            setMobilePane('chat')
            setSidebarOpen(false)
          }}
          onDeleteItem={deleteChat}
          footerLabel="Current document"
          footerIcon={<FileText size={18} />}
          footerTitle={current?.file_name || 'No document open'}
          footerMeta={
            current?.page_count ? `${current.page_count} pages indexed` : 'Upload a file to begin'
          }
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
