import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import {
  BookOpen,
  ClipboardList,
  Layers,
  Loader2,
  MessageSquarePlus,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Wand2,
} from 'lucide-react'
import axios from 'axios'
import { API_BASE_URL } from '../../config'
import { protectCurrency } from '../../lib/markdownText'
import 'katex/dist/katex.min.css'

/* The chat panel, built to the reference: a head with the assistant identity, a
   scrolling conversation, and a composer with quick-action chips.

   Answers are still real: markdown, KaTeX for maths, and every `p. N` becomes a
   pink citation button that jumps the viewer to that page. */

const PAGE_RE = /^[\[(]?\s*p\.\s*(\d{1,4})\s*[\])]?$/i

function normaliseCitations(text) {
  return String(text || '').replace(/\[\s*(p\.\s*\d{1,4})\s*\]/gi, '`$1`')
}

function buildMarkdownComponents(onJump, label) {
  function Code({ children, className }) {
    const text = String(children)
    const fenced = typeof className === 'string' && className.startsWith('language-')
    const match = fenced ? null : PAGE_RE.exec(text.trim())
    if (match) {
      const page = Number(match[1])
      return (
        <button type="button" className="citation" onClick={() => onJump?.(page)}>
          <BookOpen size={11} />
          {label(page)}
        </button>
      )
    }
    return <code className={className}>{children}</code>
  }
  return { code: Code }
}

// GFM on top of the maths: answers routinely come back with a pipe table, and
// without it the pipes and dashes were printed as text.
const remarkPlugins = [remarkGfm, remarkMath]
const rehypePlugins = [rehypeKatex]

export default function WorkspaceChat({
  document: doc,
  chatId,
  title,
  onCreateChat,
  onNewChat,
  onChatChanged,
  onJumpToPage,
}) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [votes, setVotes] = useState({})
  const scrollRef = useRef(null)

  const greek = doc?.language === 'Greek'
  const pageLabel = (page) => `${greek ? 'Σελίδα' : 'Page'} ${page}`
  const markdownComponents = buildMarkdownComponents(onJumpToPage, pageLabel)

  useEffect(() => {
    let cancelled = false
    setMessages([])
    setError('')
    if (!doc?.doc_id || !chatId) return undefined

    axios
      .get(`${API_BASE_URL}/api/document/${doc.doc_id}/chats/${chatId}`, { timeout: 30000 })
      .then(({ data }) => {
        if (cancelled) return
        setMessages(
          (data.messages || []).map((message) => ({
            role: message.role,
            content: message.content,
          })),
        )
      })
      .catch((loadError) => console.error('[Chats] load failed', loadError))

    return () => {
      cancelled = true
    }
  }, [chatId, doc?.doc_id])

  useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])

  async function ensureChat() {
    if (chatId) return chatId
    return onCreateChat()
  }

  async function send(override) {
    const question = (override ?? input).trim()
    if (!question || busy || !doc) return

    setError('')
    setInput('')
    setBusy(true)
    const history = messages
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .slice(-6)
      .map(({ role, content }) => ({ role, content }))

    setMessages((current) => [...current, { role: 'user', content: question }])

    try {
      const target = await ensureChat()
      const { data } = await axios.post(
        `${API_BASE_URL}/api/document/ask`,
        { question, doc_id: doc.doc_id, chat_id: target, history },
        { timeout: 300000 },
      )
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: normaliseCitations(data.answer || '') },
      ])
      onChatChanged?.()
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

  async function runStudy(kind) {
    if (busy || !doc) return
    setBusy(true)
    setError('')
    const label =
      kind === 'quiz'
        ? 'Make practice questions'
        : kind === 'cards'
          ? 'Make flashcards'
          : 'Write a study guide'
    setMessages((current) => [...current, { role: 'user', content: label }])

    try {
      const endpoint = kind === 'quiz' ? 'quiz' : kind === 'cards' ? 'flashcards' : 'notes'
      const { data } = await axios.post(
        `${API_BASE_URL}/api/document/${endpoint}`,
        { doc_id: doc.doc_id },
        { timeout: 300000 },
      )

      let markdown = ''
      if (kind === 'quiz') {
        const questions = data.questions || []
        const answerLabel = greek ? 'Απάντηση' : 'Answer'
        const figures = (data.figures || []).length
          ? `### ${greek ? 'Σχήματα του εγγράφου' : 'Figures in the document'}\n\n${(data.figures || [])
              .map(
                (figure) =>
                  `**p. ${figure.page}**\n\n\`\`\`\n${String(figure.text).slice(0, 1600)}\n\`\`\``,
              )
              .join('\n\n')}\n\n---\n\n`
          : ''
        markdown =
          figures +
          (questions.length
            ? questions
                .map((question, index) => {
                  const options = question.options
                    .map((option, optionIndex) => `${'ABCD'[optionIndex]}. ${option}`)
                    .join('\n\n')
                  const answer = `**${answerLabel}: ${'ABCD'[question.answer]}**${
                    question.page ? ` — \`p. ${question.page}\`` : ''
                  }${question.explain ? `\n\n${question.explain}` : ''}`
                  return `### ${index + 1}. ${question.question}\n\n${options}\n\n${answer}`
                })
                .join('\n\n---\n\n')
            : 'No questions could be built from this document.')
      } else if (kind === 'cards') {
        const cards = data.cards || []
        markdown = cards.length
          ? `### Flashcards\n\n${cards
              .map(
                (card) =>
                  `- **${card.term}**: ${card.definition}${card.page ? ` (\`p. ${card.page}\`)` : ''}`,
              )
              .join('\n')}`
          : 'No flashcards could be built from this document.'
      } else {
        markdown = data.notes || 'No study guide could be written for this document.'
      }

      setMessages((current) => [
        ...current,
        { role: 'assistant', content: normaliseCitations(markdown) },
      ])
    } catch (requestError) {
      console.error(requestError)
      setError('Could not build the study material.')
    } finally {
      setBusy(false)
    }
  }

  const empty = messages.length === 0

  return (
    <article className="panel chat-panel">
      <div className="panel-head">
        <div className="chat-heading">
          <div className="chat-icon">
            <Sparkles size={15} />
          </div>
          <div className="chat-info">
            <span className="head-label">Ask Chronomark</span>
            <small>
              <i />
              Page-linked responses
            </small>
          </div>
        </div>
        <div className="chat-actions">
          <button
            type="button"
            className="icon-btn"
            title="New chat (upload another document)"
            onClick={onNewChat || onCreateChat}
          >
            <MessageSquarePlus size={16} />
          </button>
        </div>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {empty && !busy ? (
          <div className="ai-welcome">
            <div className="welcome-logo">
              <Sparkles size={15} />
            </div>
            <div>
              <h2>Ask this document anything</h2>
              <p>
                {title ? `“${title}”` : 'Start a conversation.'} Answers come from the pages you
                uploaded, each with a page you can open.
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
                  {protectCurrency(message.content)}
                </Markdown>
              </div>
              <div className="answer-tools">
                <button
                  type="button"
                  className={`icon-btn${votes[index] === 'up' ? ' on' : ''}`}
                  aria-label="Good answer"
                  onClick={() =>
                    setVotes((current) => ({ ...current, [index]: current[index] === 'up' ? null : 'up' }))
                  }
                >
                  <ThumbsUp size={13} />
                </button>
                <button
                  type="button"
                  className={`icon-btn${votes[index] === 'down' ? ' on' : ''}`}
                  aria-label="Poor answer"
                  onClick={() =>
                    setVotes((current) => ({ ...current, [index]: current[index] === 'down' ? null : 'down' }))
                  }
                >
                  <ThumbsDown size={13} />
                </button>
              </div>
            </div>
          ),
        )}

        {busy ? (
          <div className="msg">
            <div className="msg-head">
              <span className="assistant-badge">
                <Loader2 size={12} className="docs-spin" />
              </span>
              Chronomark
            </div>
            <div className="answer">
              <p>Reading the pages…</p>
            </div>
          </div>
        ) : null}

        {error ? <p className="chat-error">{error}</p> : null}
      </div>

      <div className="composer-wrap">
        <div className="suggestions">
          <button
            type="button"
            className="prompt-chip"
            disabled={busy}
            onClick={() => send('Summarize this document')}
          >
            <Sparkles size={12} /> Summarize
          </button>
          <button type="button" className="prompt-chip" disabled={busy} onClick={() => runStudy('quiz')}>
            <ClipboardList size={12} /> Practice questions
          </button>
          <button type="button" className="prompt-chip" disabled={busy} onClick={() => runStudy('cards')}>
            <Layers size={12} /> Flashcards
          </button>
          <button
            type="button"
            className="prompt-chip"
            disabled={busy}
            onClick={() =>
              send('Explain this page in simpler words, with one concrete example and page citations.')
            }
          >
            <Wand2 size={12} /> Explain this page
          </button>
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
            placeholder="Ask anything about this document…"
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

        <p className="disclaimer">Answers are generated from the document you opened.</p>
      </div>
    </article>
  )
}
