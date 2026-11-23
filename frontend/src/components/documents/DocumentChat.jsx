import { useEffect, useRef, useState } from 'react'
import { ListChecks, Loader2, Send, Sparkles } from 'lucide-react'
import axios from 'axios'
import ChatMessages from '../ChatMessages'
import { API_BASE_URL } from '../../config'
import '../../styles/chatbot.css'
import '../../styles/chatTheme.css'

/* The document chat.

   Renders the conversation open in the sidebar, sends the next question, and asks
   the parent to refresh the sidebar once a chat gains a title or a new one is
   created. Answers are drawn by the shared chat renderer, so a document answer
   keeps the same headings, KaTeX and clickable `p. N` citations as a video one. */

const SUGGESTIONS = [
  { key: 'summary', label: 'Summarize this document', prompt: 'Summarize this document' },
  { key: 'quiz', label: 'Practice questions' },
  { key: 'cards', label: 'Flashcards' },
  { key: 'notes', label: 'Study guide' },
]

function normaliseCitations(text) {
  return String(text || '').replace(/\[\s*(p\.\s*\d{1,4})\s*\]/gi, '`$1`')
}

export default function DocumentChat({
  document: doc,
  chatId,
  onCreateChat,
  onChatChanged,
  onJumpToPage,
}) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [busyTool, setBusyTool] = useState('')
  const [error, setError] = useState('')
  const scrollRef = useRef(null)

  const isLoading = busy || !!busyTool

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
            pages: message.pages,
          })),
        )
      })
      .catch((loadError) => {
        if (cancelled) return
        console.error('[Chats] could not load the conversation', loadError)
      })

    return () => {
      cancelled = true
    }
  }, [chatId, doc?.doc_id])

  useEffect(() => {
    // Scroll the conversation itself, not the window: scrollIntoView on a
    // sentinel drags the whole page down and hides the workspace header.
    const node = scrollRef.current
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' })
  }, [messages, isLoading])

  async function ensureChat() {
    if (chatId) return chatId
    return onCreateChat()
  }

  async function send(override) {
    const question = (override ?? input).trim()
    if (!question || isLoading || !doc) return

    setError('')
    setInput('')
    setBusy(true)

    const history = messages
      .filter((message) => message.role && message.content)
      .slice(-6)
      .map((message) => ({ role: message.role, content: message.content }))

    setMessages((current) => [...current, { role: 'user', content: question }])

    try {
      const targetChat = await ensureChat()
      const { data } = await axios.post(
        `${API_BASE_URL}/api/document/ask`,
        { question, doc_id: doc.doc_id, chat_id: targetChat, history },
        { timeout: 300000 },
      )
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: normaliseCitations(data.answer || ''), pages: data.pages },
      ])
      onChatChanged?.()
    } catch (requestError) {
      const detail =
        requestError?.response?.data?.detail ||
        requestError?.message ||
        'The answer could not be generated.'
      setError(detail)
      setMessages((current) => [...current, { role: 'assistant', content: '', error: true }])
    } finally {
      setBusy(false)
    }
  }

  async function runStudy(kind) {
    if (isLoading || !doc) return
    setBusyTool(kind)
    setError('')
    const label =
      kind === 'quiz'
        ? 'Make practice questions'
        : kind === 'cards'
          ? 'Make flashcards'
          : 'Write a study guide'
    setMessages((current) => [
      ...current,
      { role: 'user', content: label },
      { role: 'assistant', content: '', loading: true },
    ])

    try {
      const endpoint = kind === 'quiz' ? 'quiz' : kind === 'cards' ? 'flashcards' : 'notes'
      const { data } = await axios.post(
        `${API_BASE_URL}/api/document/${endpoint}`,
        { doc_id: doc.doc_id },
        { timeout: 300000 },
      )

      const greek = doc?.language === 'Greek'
      let markdown = ''
      if (kind === 'quiz') {
        const questions = data.questions || []
        const answerLabel = greek ? 'Απάντηση' : 'Answer'
        const figureLabel = greek ? 'Σχήματα του εγγράφου' : 'Figures in the document'
        const figures = (data.figures || []).length
          ? `### ${figureLabel}\n\n${(data.figures || [])
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

      setMessages((current) => {
        const next = [...current]
        next[next.length - 1] = { role: 'assistant', content: normaliseCitations(markdown) }
        return next
      })
    } catch (requestError) {
      console.error(requestError)
      setMessages((current) => {
        const next = [...current]
        next[next.length - 1] = {
          role: 'assistant',
          content: 'Could not build the study material.',
          error: true,
        }
        return next
      })
    } finally {
      setBusyTool('')
    }
  }

  const empty = messages.length === 0

  return (
    <section className="docs-chat chatbot">
      <div className="docs-chat-scroll" ref={scrollRef}>
        {empty && !isLoading ? (
          <div className="docs-welcome">
            <span className="docs-welcome-icon">
              <Sparkles size={16} />
            </span>
            <div>
              <h2>Ask this document anything</h2>
              <p>
                Every answer comes from the pages you uploaded and ends with a clickable page
                reference. Nothing is presented that the document does not support.
              </p>
            </div>
          </div>
        ) : null}

        <ChatMessages
          messages={messages}
          isLoading={isLoading}
          onSeek={onJumpToPage}
          citationLabel={(pageNumber) =>
            `${doc?.language === 'Greek' ? 'Σελίδα' : 'Page'} ${pageNumber}`
          }
          onFollowUp={(text) => send(text)}
          actionLabel={(kind) => {
            const greek = doc?.language === 'Greek'
            if (kind === 'explain') return greek ? 'Εξήγησέ το αλλιώς' : 'Explain this'
            if (kind === 'good') return greek ? 'Καλή απάντηση' : 'Good answer'
            return greek ? 'Κακή απάντηση' : 'Poor answer'
          }}
        />
      </div>

      {error ? <p className="docs-chat-error">{error}</p> : null}

      <div className="docs-composer-wrap">
        <div className="docs-suggestions">
          {SUGGESTIONS.map(({ key, label, prompt }) => (
            <button
              key={key}
              type="button"
              className="docs-prompt-chip"
              disabled={isLoading}
              onClick={() => (prompt ? send(prompt) : runStudy(key))}
            >
              {busyTool === key ? <Loader2 size={12} className="docs-spin" /> : null}
              {label}
            </button>
          ))}
        </div>

        <form
          className="docs-composer"
          onSubmit={(event) => {
            event.preventDefault()
            send()
          }}
        >
          <textarea
            rows={1}
            value={input}
            placeholder="Ask about a page, a definition, an example…"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
          />
          <div className="docs-composer-bottom">
            <span className="docs-composer-hint">
              <ListChecks size={11} />
              Enter to send, Shift+Enter for a new line
            </span>
            <button type="submit" className="docs-send" disabled={isLoading || !input.trim()}>
              {isLoading ? <Loader2 size={14} className="docs-spin" /> : <Send size={14} />}
            </button>
          </div>
        </form>
      </div>
    </section>
  )
}
