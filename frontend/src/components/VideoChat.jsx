import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import { Loader2, MessageSquarePlus, Send, Sparkles, ThumbsDown, ThumbsUp } from 'lucide-react'
import axios from 'axios'
import { API_BASE_URL } from '../config'
import { protectCurrency } from '../lib/markdownText'
import 'katex/dist/katex.min.css'
import '../styles/documentsReference.css'

/* The video chat, wearing the document chat's clothes.

   The markup, class names and spacing are the ones the document workspace uses
   (.panel.chat-panel, .chat-scroll, .msg, .answer, .composer), so the two
   conversations are the same object at the same size -- the styles come from
   documentsReference.css, not from a second theme that drifts.

   What changes is the wire: questions go to /ask with a video_id, and a [mm:ss]
   marker in an answer is a button that seeks the player. */

const TIMESTAMP_RE = /^\[?(\d{1,2}):(\d{2})\]?$/

function secondsOf(text) {
  const match = TIMESTAMP_RE.exec(String(text || '').trim())
  if (!match) return null
  return Number(match[1]) * 60 + Number(match[2])
}

function buildMarkdownComponents(onSeek) {
  function Code({ children, className }) {
    const text = String(children)
    const fenced = typeof className === 'string' && className.startsWith('language-')
    const seconds = fenced ? null : secondsOf(text)
    if (seconds != null) {
      const label = text.trim().replace(/^\[|\]$/g, '')
      return (
        <button type="button" className="citation" onClick={() => onSeek?.(seconds)}>
          <Sparkles size={11} />
          {label}
        </button>
      )
    }
    return <code className={className}>{children}</code>
  }
  return { code: Code }
}

const remarkPlugins = [remarkGfm, remarkMath]
const rehypePlugins = [rehypeKatex]

const SUGGESTIONS = [
  ['Summarize this video', 'Summarize this video'],
  ['Key moments', 'List the key moments of this video with their timestamps.'],
  ['Explain simply', 'Explain the main idea of this video in simpler words.'],
]

export default function VideoChat({ videoId, onSeek, onNewVideo }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [votes, setVotes] = useState({})
  const scrollRef = useRef(null)

  const markdownComponents = buildMarkdownComponents(onSeek)
  const empty = messages.length === 0
  const streaming = false

  useEffect(() => {
    setMessages([])
    setError('')
  }, [videoId])

  useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])

  async function send(override) {
    const question = (override ?? input).trim()
    if (!question || busy || !videoId) return

    setError('')
    setInput('')
    setBusy(true)
    const history = messages
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .slice(-6)
      .map(({ role, content }) => ({ role, content }))

    setMessages((current) => [...current, { role: 'user', content: question }])

    try {
      const { data } = await axios.post(
        `${API_BASE_URL}/ask`,
        { question, video_id: videoId, history },
        { timeout: 300000 },
      )
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: protectCurrency(data.answer || '') },
      ])
    } catch (requestError) {
      setError(
        requestError?.response?.data?.detail ||
          requestError?.message ||
          'The answer could not be generated.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="panel chat-panel">
      <div className="chat-scroll" ref={scrollRef}>
        {empty && !busy ? (
          <div className="ai-welcome">
            <div className="welcome-logo">
              <Sparkles size={15} />
            </div>
            <div>
              <h2>Ask this recording anything</h2>
              <p>
                Answers come from the transcript, each with the second it came from — and the
                player follows.
              </p>
            </div>
          </div>
        ) : null}

        {messages.map((message, index) =>
          message.role === 'user' ? (
            <div key={index} className="msg user">
              <div className="bubble">{message.content}</div>
            </div>
          ) : (
            <div key={index} className="msg">
              <div className="msg-head">
                <span className="assistant-badge">
                  <Sparkles size={12} />
                </span>
                Chronomark
              </div>
              <div className="answer">
                <Markdown
                  remarkPlugins={remarkPlugins}
                  rehypePlugins={rehypePlugins}
                  components={markdownComponents}
                >
                  {message.content}
                </Markdown>
              </div>
              <div className="answer-tools">
                <button
                  type="button"
                  className={`icon-btn${votes[index] === 'up' ? ' on' : ''}`}
                  aria-label="Good answer"
                  onClick={() =>
                    setVotes((current) => ({
                      ...current,
                      [index]: current[index] === 'up' ? null : 'up',
                    }))
                  }
                >
                  <ThumbsUp size={13} />
                </button>
                <button
                  type="button"
                  className={`icon-btn${votes[index] === 'down' ? ' on' : ''}`}
                  aria-label="Poor answer"
                  onClick={() =>
                    setVotes((current) => ({
                      ...current,
                      [index]: current[index] === 'down' ? null : 'down',
                    }))
                  }
                >
                  <ThumbsDown size={13} />
                </button>
              </div>
            </div>
          ),
        )}

        {busy && !streaming ? (
          <div className="msg">
            <div className="msg-head">
              <span className="assistant-badge">
                <Loader2 size={12} className="docs-spin" />
              </span>
              Chronomark
            </div>
            <div className="answer">
              <p>Reading the transcript…</p>
            </div>
          </div>
        ) : null}

        {error ? <p className="chat-error">{error}</p> : null}
      </div>

      <div className="composer-wrap">
        <div className="suggestions">
          {SUGGESTIONS.map(([label, prompt]) => (
            <button
              key={label}
              type="button"
              className="prompt-chip"
              disabled={busy}
              onClick={() => send(prompt)}
            >
              <Sparkles size={12} /> {label}
            </button>
          ))}
        </div>

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault()
            send()
          }}
        >
          <textarea
            rows={1}
            value={input}
            placeholder="Ask anything about this recording…"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
          />
          <div className="composer-bottom">
            <span className="composer-hint">Enter to send · Shift+Enter for a new line</span>
            <button type="submit" className="send" disabled={busy || !input.trim()} aria-label="Send">
              {busy ? <Loader2 size={14} className="docs-spin" /> : <Send size={14} />}
            </button>
          </div>
        </form>

        <p className="disclaimer">Answers are generated from this recording's transcript.</p>
      </div>
    </article>
  )
}
