import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { API_BASE_URL } from '../../config'
import useAuth from '../../hooks/useAuth'
import { displayNameOf, supabase, AUTH_ENABLED } from '../../lib/supabaseClient'
import { Plus } from 'lucide-react'
import AppSidebar from '../common/AppSidebar.jsx'
import '../../styles/workspaces.css'
import '../../styles/workspaceDesign.css'

/* axios does not go through the fetch wrapper that attaches the session token,
   so every call here carries the access token itself. Without it the API
   answers 401 and the workspace shows an error instead of the user's library. */
async function authHeaders() {
  if (!AUTH_ENABLED) return {}
  try {
    const { data } = await supabase.auth.getSession()
    const token = data?.session?.access_token
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

/* The workspace, drawn from the supplied markup.

   The shell is the reference's: ambient glow over a dot grid, the 288px sidebar
   with the gradient tile, the storage line, the profile card, and the 64px
   header with breadcrumb, search, help and notifications. The main column is a
   centred hero over a dashed drop capsule, then the three value pills.

   What is wired to the product rather than the mockup: the drop zone and the
   Document Analysis button open a real picker and run the real indexing job,
   Video Analysis opens the recording workspace, the profile card is the signed
   in account, and the counts and storage are read from /api/documents. The
   Sample button says what it is -- a sample is not part of this workspace yet. */

const ACCEPT = ['.pdf', '.pptx', '.docx']
const MAX_BYTES = 40 * 1024 * 1024

const NAV = [
  ['dashboard', 'Dashboard'],
  ['new', 'New Analysis'],
  ['documents', 'My Documents'],
  ['history', 'Analysis History'],
  ['settings', 'Settings'],
]

const STEPS = [
  ['01', 'OCR & Slide Vision', 'Scans chalkboards, mathematical notations & equations automatically.'],
  ['02', 'Exact Chronomarks', 'Every AI answer anchors directly to page, slide, or spoken timestamp.'],
  ['03', 'Study Tools', 'Notes, quizzes and flashcards are built from the same pages you uploaded.'],
]

const STAGE_COPY = {
  queued: 'Preparing the upload',
  parsing: 'Reading the pages',
  chunking: 'Splitting the text',
  reading_figures: 'Reading the figures',
  embedding: 'Building the index',
  finalizing: 'Finishing up',
  summarising: 'Writing the summary',
}

const ICONS = {
  dashboard:
    'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6',
  new: 'M12 3v18M3 12h18M12 3a9 9 0 000 18 9 9 0 000-18z',
  documents:
    'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
  history: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
  settings:
    'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
}

const LABELS = Object.fromEntries(NAV)

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(Number(value) * 1000)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

function relativeDay(value) {
  if (!value) return 'Earlier'
  const days = (Date.now() / 1000 - Number(value)) / 86400
  if (days < 1) return 'Today'
  if (days < 7) return 'Previous 7 days'
  return 'Earlier'
}

function readStored(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key)
    return raw === null ? fallback : JSON.parse(raw)
  } catch {
    return fallback
  }
}

export default function Workspaces() {
  const navigate = useNavigate()
  const { session, signOut } = useAuth()

  const [view, setView] = useState('dashboard')
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => readStored('cm.ws.collapsed', false))
  const [query, setQuery] = useState('')

  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState('')
  const [progress, setProgress] = useState(0)
  const [uploadError, setUploadError] = useState('')
  const [notice, setNotice] = useState('')

  const inputRef = useRef(null)
  const pollRef = useRef(null)

  const name = displayNameOf(session)
  const email = session?.user?.email || ''
  const initials = (name || email || '?').slice(0, 2).toUpperCase()

  useEffect(() => {
    window.localStorage.setItem('cm.ws.collapsed', JSON.stringify(collapsed))
  }, [collapsed])

  useEffect(
    () => () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    },
    [],
  )

  const loadDocuments = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/documents`, {
        timeout: 30000,
        headers: await authHeaders(),
      })
      setDocuments(data.documents || [])
      setListError('')
    } catch (error) {
      setListError(error?.response?.data?.detail || 'Could not load your documents.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  const go = (id) => {
    setView(id)
    setDrawerOpen(false)
    setNotice('')
    if (id !== 'documents') setQuery('')
  }

  const search = (value) => {
    setQuery(value)
    if (value) setView('documents')
  }

  const upload = useCallback(
    async (file) => {
      if (!file || busy) return
      const suffix = `.${String(file.name.split('.').pop() || '').toLowerCase()}`
      if (!ACCEPT.includes(suffix)) {
        setUploadError('Only PDF, DOCX and PPTX are read here. Recordings go to video analysis.')
        return
      }
      if (file.size > MAX_BYTES) {
        setUploadError('That file is larger than 40 MB.')
        return
      }

      setUploadError('')
      setBusy(true)
      setProgress(0)
      setStage('queued')

      try {
        const form = new FormData()
        form.append('file_upload', file, file.name)

        const { data } = await axios.post(`${API_BASE_URL}/api/upload-document`, form, {
          timeout: 300000,
          headers: await authHeaders(),
          onUploadProgress: (event) => {
            if (!event.total) return
            setProgress(Math.min(12, Math.round((event.loaded / event.total) * 12)))
          },
        })

        setStage('parsing')
        const pollHeaders = await authHeaders()
        await new Promise((resolve, reject) => {
          pollRef.current = window.setInterval(async () => {
            try {
              const status = await axios.get(`${API_BASE_URL}/upload-status/${data.job_id}`, {
                timeout: 20000,
                headers: pollHeaders,
              })
              const job = status.data
              if (job.progress) setProgress(Math.max(12, Math.min(99, job.progress)))
              if (job.stage) setStage(job.stage)
              if (job.status === 'completed') {
                window.clearInterval(pollRef.current)
                pollRef.current = null
                resolve()
              } else if (job.status === 'failed') {
                window.clearInterval(pollRef.current)
                pollRef.current = null
                reject(new Error(job.error || 'Processing failed.'))
              }
            } catch (pollError) {
              console.error('[Workspace] status poll failed', pollError)
            }
          }, 2000)
        })

        setProgress(100)
        await loadDocuments()
        navigate(`/documents?doc=${encodeURIComponent(data.doc_id)}`)
      } catch (error) {
        setUploadError(
          error?.response?.data?.detail || error?.message || 'The upload did not go through.',
        )
      } finally {
        if (pollRef.current) window.clearInterval(pollRef.current)
        pollRef.current = null
        setBusy(false)
        setStage('')
        setProgress(0)
        if (inputRef.current) inputRef.current.value = ''
      }
    },
    [busy, loadDocuments, navigate],
  )

  const onDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer?.files?.[0]
    if (file) upload(file)
  }

  const removeDocument = async (docId) => {
    if (!window.confirm('Delete this document and its conversations?')) return
    try {
      await axios.delete(`${API_BASE_URL}/api/document/${docId}`, {
        timeout: 30000,
        headers: await authHeaders(),
      })
      setDocuments((list) => list.filter((item) => item.doc_id !== docId))
      setNotice('Document deleted.')
    } catch (error) {
      setListError(error?.response?.data?.detail || 'Could not delete that document.')
    }
  }

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return documents
    return documents.filter((item) => String(item.file_name || '').toLowerCase().includes(needle))
  }, [documents, query])

  const history = useMemo(() => {
    const groups = new Map()
    filtered.forEach((item) => {
      const key = relativeDay(item.created_at)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(item)
    })
    return [...groups.entries()]
  }, [filtered])

  const openDoc = (docId) => navigate(`/documents?doc=${encodeURIComponent(docId)}`)

  return (
    <div className={`wref${collapsed ? ' is-collapsed' : ''}${drawerOpen ? ' is-drawer' : ''}`}>

      <div className="wr-glow" aria-hidden="true">
        <div className="wr-glow-a" />
        <div className="wr-glow-b" />
        <div className="wr-grid" />
      </div>

      <AppSidebar
        collapsed={collapsed}
        open={drawerOpen}
        onToggle={() => setCollapsed((value) => !value)}
        onClose={() => setDrawerOpen(false)}
        brandHref="/workspaces"
        actions={[
          {
            key: 'new',
            icon: Plus,
            label: 'New analysis',
            title: 'Upload a document',
            primary: true,
            onClick: () => inputRef.current?.click(),
          },
        ]}
        search={{ placeholder: 'Search your documents', label: 'Search documents' }}
        items={documents.map((doc) => ({
          id: doc.doc_id,
          title: doc.file_name,
          updated_at: doc.created_at,
        }))}
        onSelectItem={openDoc}
        onDeleteItem={removeDocument}
        emptyText="No documents yet. Ask something to start one."
        footerLabel="Signed in"
        footerIcon={<span className="sidebar-avatar">{initials}</span>}
        footerTitle={name || 'Signed in'}
        footerMeta={email || ''}
      />

      <main className="wr-main">
        <header className="wr-topbar">
          <div className="wr-crumbs">
            <button type="button" onClick={() => go('dashboard')}>Workspace</button>
            <span aria-hidden="true">/</span>
            <span className="wr-crumb-current">
              <i aria-hidden="true" />
              {LABELS[view] || 'Dashboard'}
            </span>
            <button
              type="button"
              className="wr-menu"
              onClick={() => setDrawerOpen(true)}
              aria-label="Open menu"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 7h16M4 12h16M4 17h16" />
              </svg>
            </button>
          </div>

          <nav className="wr-views" aria-label="Workspace views">
            {NAV.map(([id, label]) => {
              const active = view === id
              return (
                <button
                  key={id}
                  type="button"
                  className={`wr-view${active ? ' is-active' : ''}`}
                  onClick={() => go(id)}
                  aria-current={active ? 'page' : undefined}
                >
                  {label}
                </button>
              )
            })}
          </nav>

          <div className="wr-tools">
            <label className="wr-search">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="search"
                value={query}
                onChange={(event) => search(event.target.value)}
                placeholder="Search your documents"
                aria-label="Search your documents"
              />
              <kbd>⌘K</kbd>
            </label>

            <a className="wr-head-link" href="/upload">
              <span>Recordings</span>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M7 17L17 7M17 7H8m9 0v9" />
              </svg>
            </a>

            <a className="wr-icon" href="/#technology" title="How it works">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </a>

            <button
              type="button"
              className="wr-icon is-dot"
              onClick={() => setNotice(notice === 'No new notifications.' ? '' : 'No new notifications.')}
              title="Notifications"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            </button>
          </div>
        </header>

        <div className={`wr-content${view === 'dashboard' || view === 'new' ? ' is-home' : ''}`}>
          {notice ? <p className="wr-notice">{notice}</p> : null}
          {listError ? <p className="wr-error" role="alert">{listError}</p> : null}

          {view === 'dashboard' || view === 'new' ? (
            <>
              <div className="wr-hero">
                <h1>
                  {view === 'new'
                    ? 'Start a new analysis.'
                    : documents.length
                      ? 'Ready for the next one.'
                      : 'Your workspace starts here.'}
                </h1>
                <p className="wr-hero-accent">Ask it anything.</p>
                <p>
                  Upload research papers, lecture recordings, or course slides. ChronoMark indexes
                  every passage with millisecond citations.
                </p>
              </div>

              <div
                className={`wr-dropwrap${dragging ? ' is-dragging' : ''}`}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                onClick={() => !busy && inputRef.current?.click()}
                onKeyDown={(event) => {
                  if (busy) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    inputRef.current?.click()
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label="Upload a document"
              >
                <div className="wr-dropglow" aria-hidden="true" />

                <div className="wr-dropcard">
                  <input
                    ref={inputRef}
                    type="file"
                    className="wr-file"
                    accept={ACCEPT.join(',')}
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) upload(file)
                    }}
                  />

                  {busy ? (
                    <div className="wr-uploading" aria-live="polite">
                      <span className="wr-tile-drop">
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                        </svg>
                      </span>
                      <h2>{STAGE_COPY[stage] || 'Working'}</h2>
                      <p className="wr-drop-sub">{progress}% · keep this tab open until the index is ready</p>
                      <div
                        className="wr-progress"
                        role="progressbar"
                        aria-valuenow={progress}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <span style={{ width: `${Math.max(3, progress)}%` }} />
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="wr-sheet-head" aria-hidden="true">
                        <span>New document</span>
                        <span>PDF · DOCX · PPTX</span>
                      </div>

                      <span className="wr-tile-drop" aria-hidden="true">
                        <svg viewBox="0 0 24 24">
                          <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                        </svg>
                      </span>

                      <h2>
                        Drop your documents here, or <span>browse files</span>
                      </h2>
                      <p className="wr-drop-sub">
                        Instant semantic extraction for lectures, symposiums, and textbooks up to
                        40 MB each.
                      </p>

                      <div className="wr-badges" aria-hidden="true">
                        <span>PDF</span>
                        <span>DOCX</span>
                        <span>PPTX</span>
                        <i />
                        <span className="is-video">MP4</span>
                        <span className="is-video">MKV / M4A</span>
                      </div>

                      <div className="wr-actions">
                        <button
                          type="button"
                          className="wr-btn-primary"
                          onClick={(event) => {
                            event.stopPropagation()
                            navigate('/documents')
                          }}
                        >
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                          </svg>
                          <span>Document Analysis</span>
                        </button>
                        <button
                          type="button"
                          className="wr-btn-secondary"
                          onClick={(event) => {
                            event.stopPropagation()
                            navigate('/upload')
                          }}
                        >
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                          </svg>
                          <span>Video Analysis</span>
                        </button>
                      </div>

                      {uploadError ? (
                        <p className="wr-error" role="alert">{uploadError}</p>
                      ) : null}
                    </>
                  )}
                </div>
              </div>

              <div className="wr-pills">
                {STEPS.map(([number, title, copy]) => (
                  <article key={number} className="wr-pill">
                    <span className="wr-pill-num">{number}</span>
                    <div>
                      <h3>{title}</h3>
                      <p>{copy}</p>
                    </div>
                  </article>
                ))}
              </div>

              {loading ? (
                <p className="wr-loading">Loading your documents…</p>
              ) : documents.length ? (
                <div className="wr-recent">
                  <div className="wr-recent-head">
                    <h3>Recently added</h3>
                    <button type="button" className="wr-text-btn" onClick={() => go('documents')}>
                      View all
                    </button>
                  </div>
                  <div className="wr-cards">
                    {documents.slice(0, 4).map((doc) => (
                      <button
                        key={doc.doc_id}
                        type="button"
                        className="wr-card"
                        onClick={() => openDoc(doc.doc_id)}
                      >
                        <span className="wr-card-name">{doc.file_name}</span>
                        <span className="wr-card-meta">
                          {doc.page_count || 0} pages · {formatDate(doc.created_at)}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}

          {view === 'documents' ? (
            <section className="wr-list">
              <div className="wr-list-head">
                <h2>
                  {query ? `Results for “${query}”` : 'All documents'}
                  <span>{filtered.length}</span>
                </h2>
                <button type="button" className="wr-btn-primary" onClick={() => go('dashboard')}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 4v16m8-8H4" />
                  </svg>
                  <span>Add document</span>
                </button>
              </div>

              {loading ? (
                <p className="wr-loading">Loading your documents…</p>
              ) : filtered.length ? (
                <ul className="wr-rows">
                  {filtered.map((doc) => (
                    <li key={doc.doc_id}>
                      <button type="button" className="wr-row" onClick={() => openDoc(doc.doc_id)}>
                        <span className="wr-row-icon" aria-hidden="true">{doc.file_name?.slice(0, 1).toUpperCase()}</span>
                        <span className="wr-row-name">{doc.file_name}</span>
                        <span className="wr-row-meta">{doc.page_count || 0} pages · {formatDate(doc.created_at)}</span>
                        <span
                          className="wr-row-delete"
                          role="button"
                          tabIndex={0}
                          onClick={(event) => {
                            event.stopPropagation()
                            removeDocument(doc.doc_id)
                          }}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                              event.stopPropagation()
                              removeDocument(doc.doc_id)
                            }
                          }}
                        >
                          Delete
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="wr-empty">
                  <h3>{query ? 'Nothing matches that search.' : 'No documents yet.'}</h3>
                  <p>{query ? 'Try a shorter word, or part of the file name.' : 'The first upload fills this page.'}</p>
                </div>
              )}
            </section>
          ) : null}

          {view === 'history' ? (
            <section className="wr-list">
              <div className="wr-list-head">
                <h2>Analysis history<span>{filtered.length}</span></h2>
              </div>

              {loading ? (
                <p className="wr-loading">Loading your history…</p>
              ) : history.length ? (
                history.map(([group, items]) => (
                  <div key={group} className="wr-history-group">
                    <h3 className="wr-group-title">{group}</h3>
                    <ul className="wr-rows">
                      {items.map((doc) => (
                        <li key={doc.doc_id}>
                          <button type="button" className="wr-row" onClick={() => openDoc(doc.doc_id)}>
                            <span className="wr-row-icon" aria-hidden="true">{doc.file_name?.slice(0, 1).toUpperCase()}</span>
                            <span className="wr-row-name">{doc.file_name}</span>
                            <span className="wr-row-meta">{doc.page_count || 0} pages · indexed</span>
                            <span className="wr-row-meta">{formatDate(doc.created_at)}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              ) : (
                <div className="wr-empty">
                  <h3>Nothing analysed yet.</h3>
                  <p>Uploads appear here with the day they were read.</p>
                </div>
              )}
            </section>
          ) : null}

          {view === 'settings' ? (
            <section className="wr-settings">
              <div className="wr-panel">
                <h3>Account</h3>
                <dl>
                  <div>
                    <dt>Name</dt>
                    <dd>{name || '—'}</dd>
                  </div>
                  <div>
                    <dt>Email</dt>
                    <dd>{email || '—'}</dd>
                  </div>
                  <div>
                    <dt>Documents</dt>
                    <dd>{documents.length}</dd>
                  </div>
                </dl>
              </div>

              <div className="wr-panel">
                <h3>Workspace</h3>
                <label className="wr-switch">
                  <span>
                    <span className="wr-switch-label">Start with the sidebar collapsed</span>
                    <span className="wr-switch-note">More room for the document. You can always expand it again.</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={collapsed}
                    onChange={(event) => setCollapsed(event.target.checked)}
                  />
                </label>
              </div>

              <div className="wr-panel">
                <h3>Session</h3>
                <p className="wr-panel-copy">
                  Signing out ends the session on this device only. Your documents stay indexed.
                </p>
                <button type="button" className="wr-btn-ghost is-solid" onClick={signOut}>
                  Sign out
                </button>
              </div>
            </section>
          ) : null}
        </div>

        <footer className="wr-footer">
          <div>{loading ? '' : `${documents.length} indexed`}</div>
          <div>{busy ? STAGE_COPY[stage] || 'Working' : 'PDF · DOCX · PPTX · MP4 · MKV · M4A'}</div>
        </footer>
      </main>
    </div>
  )
}
