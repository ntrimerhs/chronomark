import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Loader2, Paperclip, Send, Video } from 'lucide-react'
import { API_BASE_URL } from '../../config'
import AppSidebar from '../common/AppSidebar.jsx'
import useLibrary from '../../hooks/useLibrary.js'
import '../../styles/workspaces.css'
import '../../styles/documentsReference.css'

/* The way in, and the only one.

   This used to be a dashboard with a drop zone, three value pills and a row of
   cards -- a page that had to explain itself before it could be used. It is now
   an empty conversation: one composer, one paperclip, and a sentence that says
   what ChronoMark does with a file once it has one.

   The file decides the workspace, not the reader. A PDF, PPTX or DOCX goes to
   /api/upload-document and lands in the document analysis; anything with sound
   or pictures goes to /uploadfile/ and lands in the video analysis with the
   player beside the chat. Both start from this same line of text. */

const DOCUMENT_SUFFIXES = ['.pdf', '.pptx', '.docx']
const AUDIOVISUAL_SUFFIXES = [
  '.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v',
  '.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac', '.opus',
]
const MAX_DOCUMENT_BYTES = 40 * 1024 * 1024
const POLL_MS = 2000

function suffixOf(name) {
  const dot = String(name || '').lastIndexOf('.')
  return dot === -1 ? '' : name.slice(dot).toLowerCase()
}

function kindOf(name) {
  const suffix = suffixOf(name)
  if (DOCUMENT_SUFFIXES.includes(suffix)) return 'document'
  if (AUDIOVISUAL_SUFFIXES.includes(suffix)) return 'video'
  return null
}

function prettyBytes(bytes) {
  if (!bytes) return '0 MB'
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export default function ChatHome() {
  const navigate = useNavigate()
  const library = useLibrary()

  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('')
  const [dragging, setDragging] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [open, setOpen] = useState(false)
  const fileRef = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current)
  }, [])

  const say = useCallback((role, text) => {
    setMessages((list) => [
      ...list,
      { id: `${role}-${list.length}-${Date.now()}`, role, text },
    ])
  }, [])

  const waitForJob = useCallback(
    (jobId) =>
      new Promise((resolve, reject) => {
        pollRef.current = window.setInterval(async () => {
          try {
            const { data } = await axios.get(`${API_BASE_URL}/upload-status/${jobId}`, {
              timeout: 20000,
            })
            if (data.progress) setProgress(Math.max(15, Math.min(99, data.progress)))
            if (data.stage) setStatus(String(data.stage).replace(/_/g, ' '))
            if (data.status === 'completed') {
              window.clearInterval(pollRef.current)
              pollRef.current = null
              resolve(data)
            } else if (data.status === 'failed') {
              window.clearInterval(pollRef.current)
              pollRef.current = null
              reject(new Error(data.error || 'Processing failed.'))
            }
          } catch (pollError) {
            console.error('[Chat] status poll failed', pollError)
          }
        }, POLL_MS)
      }),
    [],
  )

  const takeFile = useCallback(
    async (file) => {
      if (!file || busy) return
      const kind = kindOf(file.name)

      if (!kind) {
        say(
          'assistant',
          'That file I cannot read. Text-shaped work arrives as PDF, PPTX or DOCX; ' +
            'sound or pictures as MP4, MKV, MOV, WEBM, MP3, M4A or WAV. ' +
            `“${file.name}” is neither.`,
        )
        return
      }
      if (kind === 'document' && file.size > MAX_DOCUMENT_BYTES) {
        say('assistant', `That document is ${prettyBytes(file.size)}; the limit is 40 MB.`)
        return
      }

      say('user', `${file.name} · ${prettyBytes(file.size)}`)
      setBusy(true)
      setProgress(0)
      setStatus('uploading')

      try {
        const form = new FormData()
        form.append('file_upload', file, file.name)
        const onUploadProgress = (event) => {
          if (!event.total) return
          setProgress(Math.min(12, Math.round((event.loaded / event.total) * 12)))
        }

        if (kind === 'document') {
          const { data } = await axios.post(`${API_BASE_URL}/api/upload-document`, form, {
            timeout: 300000,
            onUploadProgress,
          })
          if (data.duplicate) {
            say('assistant', 'That document is already open — I had it from a moment ago.')
            navigate(`/workspaces?doc=${encodeURIComponent(data.doc_id)}`)
            return
          }
          setStatus('parsing')
          await waitForJob(data.job_id)
          setProgress(100)
          navigate(`/workspaces?doc=${encodeURIComponent(data.doc_id)}`)
          return
        }

        const { data } = await axios.post(`${API_BASE_URL}/uploadfile/`, form, {
          timeout: 3600000,
          onUploadProgress,
        })
        setStatus('transcribing')
        await waitForJob(data.job_id)
        setProgress(100)
        navigate(`/workspaces?video=${encodeURIComponent(data.video_id)}`)
      } catch (error) {
        const detail =
          error?.response?.data?.detail || error?.message || 'The upload did not go through.'
        say('assistant', `The upload stopped: ${detail}`)
      } finally {
        if (pollRef.current) window.clearInterval(pollRef.current)
        pollRef.current = null
        setBusy(false)
        setProgress(0)
        setStatus('')
        if (fileRef.current) fileRef.current.value = ''
      }
    },
    [busy, navigate, say, waitForJob],
  )

  const send = useCallback(() => {
    const text = draft.trim()
    if (!text) return
    say('user', text)
    setDraft('')
    // There is nothing to answer from yet, and pretending otherwise would be a
    // lie produced by a model instead of an empty page.
    say(
      'assistant',
      'I have nothing to read yet. Send me a PDF, PPTX or DOCX to analyse as pages, ' +
        'or a recording (MP4, MKV, MOV, WEBM, M4A, MP3) to analyse as audio and frames — ' +
        'the paperclip, or drop the file on this window. Then ask me anything about it.',
    )
  }, [draft, say])

  const onDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer?.files?.[0]
    if (file) takeFile(file)
  }

  const items = [
    ...library.documents.map((doc) => ({
      id: doc.doc_id,
      title: doc.file_name || 'Untitled document',
      updated_at: doc.created_at,
      group: 'Library',
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
  ]

  return (
    <div className="docs-app dark">
      <div className="app-layout">
        <AppSidebar
        collapsed={collapsed}
        open={open}
        onToggle={() => setCollapsed((value) => !value)}
        onClose={() => setOpen(false)}
        actions={[
          {
            key: 'new',
            icon: Paperclip,
            label: 'New analysis',
            title: 'Start with a file',
            primary: true,
            onClick: () => fileRef.current?.click(),
          },
        ]}
        items={items}
        onSelectItem={(id) => {
          const key = String(id || '')
          if (key.startsWith('doc_')) {
            navigate(`/workspaces?doc=${encodeURIComponent(key)}`)
          } else {
            navigate(`/workspaces?video=${encodeURIComponent(key)}`)
          }
        }}
        search={{ placeholder: 'Search your library', label: 'Search your library' }}
        emptyText="Nothing analysed yet. Send a file to begin."
      />

      <main
        className={`ch-main${dragging ? ' is-dragging' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={fileRef}
          className="ch-file"
          type="file"
          accept={`${DOCUMENT_SUFFIXES.join(',')},${AUDIOVISUAL_SUFFIXES.join(',')}`}
          onChange={(event) => takeFile(event.target.files?.[0])}
        />

        <div className="ch-thread">
          {messages.length === 0 ? (
            <div className="ch-empty">
              <h1>What are we reading?</h1>
              <p>
                Drop a paper, a deck or a recording here. ChronoMark indexes every passage,
                slide and spoken second, and answers with the page or the moment it came from.
              </p>
            </div>
          ) : (
            messages.map((message) => (
              <div key={message.id} className={`ch-turn ch-turn-${message.role}`}>
                <span className="ch-who">{message.role === 'user' ? 'You' : 'ChronoMark'}</span>
                <p>{message.text}</p>
              </div>
            ))
          )}

          {busy ? (
            <div className="ch-turn ch-turn-assistant">
              <span className="ch-who">
                <Loader2 size={13} className="ch-spin" /> ChronoMark
              </span>
              <p>
                {status || 'working'} · {progress}%
              </p>
              <div className="ch-bar">
                <span style={{ width: `${progress}%` }} />
              </div>
            </div>
          ) : null}
        </div>

        <div className="ch-composer">
          <button
            type="button"
            className="ch-attach"
            title="Attach a document or a recording"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            <Paperclip size={16} />
          </button>
          <textarea
            className="ch-input"
            rows={1}
            placeholder="Ask a question, or drop a file — PDF, DOCX, PPTX, MP4, MKV, M4A…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            disabled={busy}
          />
          <button
            type="button"
            className="ch-send"
            onClick={send}
            disabled={busy || !draft.trim()}
            title="Send"
          >
            <Send size={15} />
          </button>
        </div>

        {dragging ? <div className="ch-drop">Let go to analyse it</div> : null}
        </main>
      </div>
    </div>
  )
}
