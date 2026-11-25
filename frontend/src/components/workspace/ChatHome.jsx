import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { ChevronLeft, ChevronRight, Loader2, Paperclip, Plus, Send, Video } from 'lucide-react'
import { API_BASE_URL } from '../../config'
import AppSidebar from '../common/AppSidebar.jsx'
import useLibrary from '../../hooks/useLibrary.js'
import '../../styles/workspaces.css'
import '../../styles/documentsReference.css'

/* One page, one shape, from the first question to the last answer.

   There is no separate analysis page any more: the file you bring, the pages it
   becomes and the conversation about it all live here. The middle of the window
   changes -- a document on the left of the thread, a recording in the same place
   -- but nothing navigates, the sidebar never reloads, and the composer is
   always the same composer. Switching from one chat to another is a click in
   the list, not a page load.

   The file decides what it becomes: PDF/PPTX/DOCX is read as pages, anything
   with sound or pictures is transcribed as audio and frames. */

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

function turnsFromChat(chat) {
  return (chat?.messages || []).map((message, index) => ({
    id: `${message.role}-${index}-${message.at || index}`,
    role: message.role === 'user' ? 'user' : 'assistant',
    text: message.content || '',
  }))
}

export default function ChatHome() {
  const library = useLibrary()

  const [matter, setMatter] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('')
  const [dragging, setDragging] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)

  const fileRef = useRef(null)
  const pollRef = useRef(null)
  const threadRef = useRef(null)
  const chatRef = useRef(null)

  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current)
  }, [])

  useEffect(() => {
    const node = threadRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages, busy])

  const say = useCallback((role, text) => {
    setMessages((list) => [
      ...list,
      { id: `${role}-${list.length}-${Date.now()}`, role, text },
    ])
  }, [])

  const reset = useCallback(() => {
    setMatter(null)
    setMessages([])
    setPage(1)
    chatRef.current = null
    setDraft('')
    if (fileRef.current) fileRef.current.value = ''
  }, [])

  const openDocument = useCallback(async (docId) => {
    setBusy(true)
    setStatus('opening')
    try {
      const [docResponse, chatsResponse] = await Promise.all([
        axios.get(`${API_BASE_URL}/api/document/${docId}`, { timeout: 30000 }),
        axios.get(`${API_BASE_URL}/api/document/${docId}/chats`, { timeout: 30000 }),
      ])
      const latest = (chatsResponse.data?.chats || [])[0]
      let turns = []
      chatRef.current = null
      if (latest) {
        const { data } = await axios.get(
          `${API_BASE_URL}/api/document/${docId}/chats/${latest.id}`,
          { timeout: 30000 },
        )
        chatRef.current = latest.id
        turns = turnsFromChat(data)
      }
      setMatter({ kind: 'document', id: docId, document: docResponse.data })
      setMessages(turns)
      setPage(1)
    } catch (error) {
      say('assistant', `I could not open that document: ${error?.response?.data?.detail || error.message}`)
    } finally {
      setBusy(false)
      setStatus('')
    }
  }, [say])

  const openVideo = useCallback(async (videoId) => {
    try {
      const { data } = await axios.get(`${API_BASE_URL}/api/videos`, { timeout: 30000 })
      const found = (data.videos || []).find((item) => item.video_id === videoId)
      if (!found) {
        say('assistant', 'That recording is not in your library any more.')
        return
      }
      setMatter({ kind: 'video', id: videoId, video: found })
      setMessages([])
      setPage(1)
    } catch (error) {
      say('assistant', `I could not open that recording: ${error?.response?.data?.detail || error.message}`)
    }
  }, [say])

  // A ?doc= or ?video= in the address is read once, on arrival: it opens that
  // chat in this same page. After that the address is left alone.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const docId = params.get('doc')
    const videoId = params.get('video')
    if (docId) openDocument(docId)
    else if (videoId) openVideo(videoId)
  }, [openDocument, openVideo])

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
          'That file I cannot read. Text arrives as PDF, PPTX or DOCX; sound or ' +
            `pictures as MP4, MKV, MOV, WEBM, MP3, M4A or WAV. “${file.name}” is neither.`,
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
            await openDocument(data.doc_id)
            say('assistant', 'That document is already open — I had it from a moment ago.')
            return
          }
          setStatus('parsing')
          await waitForJob(data.job_id)
          setProgress(100)
          await openDocument(data.doc_id)
          await library.refresh()
          return
        }

        const { data } = await axios.post(`${API_BASE_URL}/uploadfile/`, form, {
          timeout: 3600000,
          onUploadProgress,
        })
        setStatus('transcribing')
        await waitForJob(data.job_id)
        setProgress(100)
        await openVideo(data.video_id)
        await library.refresh()
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
    [busy, library, openDocument, openVideo, say, waitForJob],
  )

  const ask = useCallback(async () => {
    const text = draft.trim()
    if (!text || busy) return
    say('user', text)
    setDraft('')

    if (!matter) {
      say(
        'assistant',
        'I have nothing to read yet. Send me a PDF, PPTX or DOCX to analyse as pages, ' +
          'or a recording (MP4, MKV, MOV, WEBM, M4A, MP3) to analyse as audio and frames — ' +
          'the paperclip, or drop the file on this window. Then ask me anything about it.',
      )
      return
    }

    setBusy(true)
    try {
      if (matter.kind === 'document') {
        let chatId = chatRef.current
        if (!chatId) {
          const { data } = await axios.post(
            `${API_BASE_URL}/api/document/${matter.id}/chats`,
            { title: text.slice(0, 60) },
            { timeout: 30000 },
          )
          chatId = data.id
          chatRef.current = chatId
        }
        const { data } = await axios.post(
          `${API_BASE_URL}/api/document/ask`,
          { doc_id: matter.id, question: text, chat_id: chatId },
          { timeout: 300000 },
        )
        say('assistant', data.answer || '')
        library.refresh()
      } else {
        const history = messages.map((message) => ({
          role: message.role,
          content: message.text,
        }))
        const { data } = await axios.post(
          `${API_BASE_URL}/ask`,
          { question: text, video_id: matter.id, history },
          { timeout: 300000 },
        )
        say('assistant', data.answer || '')
      }
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || 'The answer failed.'
      say('assistant', `I could not answer that: ${detail}`)
    } finally {
      setBusy(false)
    }
  }, [busy, draft, library, matter, messages, say])

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
      active: matter?.kind === 'document' && matter.id === doc.doc_id,
      deletable: false,
    })),
    ...library.videos.map((video) => ({
      id: video.video_id,
      title: video.title || 'Recording',
      updated_at: video.created_at,
      group: 'Library',
      icon: Video,
      active: matter?.kind === 'video' && matter.id === video.video_id,
      deletable: false,
    })),
  ]

  const totalPages = matter?.document?.page_count || 1
  const fileUrl = matter?.document?.file_url ? `${API_BASE_URL}${matter.document.file_url}` : ''
  const videoUrl =
    matter?.kind === 'video' && matter.video?.file_key
      ? `${API_BASE_URL}/api/video-stream/${matter.video.file_key}`
      : ''

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
              icon: Plus,
              label: 'New analysis',
              title: 'Start with a file',
              primary: true,
              onClick: () => {
                reset()
                setOpen(false)
                fileRef.current?.click()
              },
            },
          ]}
          items={items}
          onSelectItem={(id) => {
            const key = String(id || '')
            if (key.startsWith('doc_')) openDocument(key)
            else openVideo(key)
            setOpen(false)
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

          <div className={`ch-split${matter ? ' has-analysis' : ''}`}>
            {matter ? (
              <section className="ch-analysis">
                <div className="ch-analysis-head">
                  <span className="ch-analysis-title" title={matter.document?.file_name || matter.video?.title}>
                    {matter.kind === 'document'
                      ? matter.document?.file_name || 'Document'
                      : matter.video?.title || 'Recording'}
                  </span>
                  {matter.kind === 'document' ? (
                    <div className="ch-pager">
                      <button
                        type="button"
                        onClick={() => setPage((value) => Math.max(1, value - 1))}
                        disabled={page <= 1}
                        title="Previous page"
                      >
                        <ChevronLeft size={14} />
                      </button>
                      <span>
                        {page} / {totalPages}
                      </span>
                      <button
                        type="button"
                        onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                        disabled={page >= totalPages}
                        title="Next page"
                      >
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  ) : null}
                </div>

                {matter.kind === 'document' ? (
                  fileUrl ? (
                    <iframe
                      key={`${fileUrl}-${page}`}
                      className="ch-page"
                      title={matter.document?.file_name || 'document'}
                      src={`${fileUrl.split('#')[0]}#page=${page}&toolbar=0&navpanes=0&view=FitH`}
                    />
                  ) : (
                    <div className="ch-expired">
                      <strong>The uploaded file has been removed</strong>
                      <p>
                        An upload is kept for three hours. The pages, the questions and this
                        conversation stay.
                      </p>
                    </div>
                  )
                ) : videoUrl ? (
                  <video className="ch-video" src={videoUrl} controls playsInline />
                ) : (
                  <div className="ch-expired">
                    <strong>The recording is not in the bucket any more</strong>
                    <p>Uploads are deleted after three hours; the transcript and this conversation stay.</p>
                  </div>
                )}
              </section>
            ) : null}

            <section className="ch-conversation">
              <div className="ch-thread" ref={threadRef}>
                {messages.length === 0 && !busy ? (
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
                      <span className="ch-who">
                        {message.role === 'user' ? 'You' : 'ChronoMark'}
                      </span>
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
                      {status || 'thinking'} · {progress}%
                    </p>
                    {progress ? (
                      <div className="ch-bar">
                        <span style={{ width: `${progress}%` }} />
                      </div>
                    ) : null}
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
                      ask()
                    }
                  }}
                  disabled={busy}
                />
                <button
                  type="button"
                  className="ch-send"
                  onClick={ask}
                  disabled={busy || !draft.trim()}
                  title="Send"
                >
                  <Send size={15} />
                </button>
              </div>
            </section>
          </div>

          {dragging ? <div className="ch-drop">Let go to analyse it</div> : null}
        </main>
      </div>
    </div>
  )
}
