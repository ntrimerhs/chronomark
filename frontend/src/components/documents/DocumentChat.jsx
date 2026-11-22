import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import ReactMarkdown from 'react-markdown'
import { BookOpen, Layers, Loader2, ListChecks, Send, Sparkles } from 'lucide-react'
import { API_BASE_URL } from '../../config'
import '../../styles/documentsTheme.css'

/* Chat for a document.

   Same conversation contract as the video chat, with one difference that comes
   from the medium: instead of timestamp pills it returns page pills, and
   clicking one scrolls the viewer to that page.

   The study tools live here too, because they are the same act as asking a
   question: read the index, answer with pages. */

const SUGGESTIONS = ['Summarize this document', 'What are the key definitions?', 'Make me practice questions']

function PagePills({ pages, onJump }) {
  if (!pages?.length) return null
  return (
    <div className="docs-pills">
      {pages.map((page) => (
        <button
          key={page.page}
          type="button"
          className="docs-pill"
          onClick={() => onJump(page.page)}
          title={page.heading || `Page ${page.page}`}
        >
          p. {page.page}
        </button>
      ))}
    </div>
  )
}

export default function DocumentChat({ document: doc, onJumpToPage }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [study, setStudy] = useState(null)
  const [studyBusy, setStudyBusy] = useState('')
  const [revealed, setRevealed] = useState({})
  const scrollRef = useRef(null)

  useEffect(() => {
    setMessages([])
    setInput('')
    setError('')
    setStudy(null)
    setRevealed({})
  }, [doc?.doc_id])

  useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages, busy])

  const history = messages
    .filter((message) => message.role === 'user' || message.role === 'assistant')
    .slice(-6)
    .map((message) => ({ role: message.role, content: message.content }))

  async function ask(question) {
    const text = (question ?? input).trim()
    if (!text || busy || !doc) return

    setBusy(true)
    setError('')
    setInput('')
    setMessages((current) => [...current, { role: 'user', content: text }])

    try {
      const { data } = await axios.post(
        `${API_BASE_URL}/api/document/ask`,
        { question: text, doc_id: doc.doc_id, history },
        { timeout: 180000 },
      )
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: data.answer || '', pages: data.pages || [] },
      ])
    } catch (requestError) {
      const detail =
        requestError?.response?.data?.detail ||
        requestError?.message ||
        'The answer could not be generated.'
      setError(detail)
      setMessages((current) => [...current, { role: 'assistant', content: '', failed: true }])
    } finally {
      setBusy(false)
    }
  }

  async function runStudy(kind) {
    if (!doc || studyBusy) return
    setStudyBusy(kind)
    setError('')
    try {
      const endpoint =
        kind === 'quiz'
          ? '/api/document/quiz'
          : kind === 'cards'
            ? '/api/document/flashcards'
            : '/api/document/notes'
      const { data } = await axios.post(
        `${API_BASE_URL}${endpoint}`,
        { doc_id: doc.doc_id },
        { timeout: 180000 },
      )
      setStudy({ kind, data })
    } catch (requestError) {
      setError(requestError?.response?.data?.detail || 'Could not build the study material.')
    } finally {
      setStudyBusy('')
    }
  }

  return (
    <section className="docs-chat">
      <header className="docs-chat-head">
        <span className="docs-chat-title">
          <Sparkles size={13} />
          Ask the document
        </span>
        <span className="docs-chat-meta">
          {doc?.kind?.toUpperCase()} · {doc?.page_count || 0} pages
        </span>
      </header>

      <div className="docs-chat-scroll" ref={scrollRef}>
        {messages.length === 0 && !busy ? (
          <div className="docs-chat-empty">
            <p>Ask anything about this handout. Answers cite the page they came from.</p>
            <div className="docs-suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button key={suggestion} type="button" onClick={() => ask(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {messages.map((message, index) =>
          message.role === 'user' ? (
            <div key={index} className="docs-message is-user">
              <p>{message.content}</p>
            </div>
          ) : (
            <div key={index} className="docs-message is-assistant">
              {message.failed ? (
                <p className="docs-chat-error">Something went wrong.</p>
              ) : (
                <div className="docs-answer">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>
              )}
              <PagePills pages={message.pages} onJump={onJumpToPage} />
            </div>
          ),
        )}

        {busy ? (
          <div className="docs-message is-assistant">
            <p className="docs-chat-thinking">
              <Loader2 size={13} className="docs-spin" /> reading the pages…
            </p>
          </div>
        ) : null}

        {error ? <p className="docs-chat-error">{error}</p> : null}

        {study ? (
          <div className="docs-study">
            <header>
              <strong>
                {study.kind === 'quiz'
                  ? 'Practice questions'
                  : study.kind === 'cards'
                    ? 'Flashcards'
                    : 'Study guide'}
              </strong>
              <button type="button" onClick={() => setStudy(null)}>
                close
              </button>
            </header>

            {study.kind === 'quiz' ? (
              <ol className="docs-quiz">
                {(study.data.questions || []).map((question, questionIndex) => (
                  <li key={questionIndex}>
                    <p className="docs-quiz-q">{question.question}</p>
                    <ul>
                      {question.options.map((option, optionIndex) => {
                        const chosen = revealed[questionIndex] === optionIndex
                        const correct = question.answer === optionIndex
                        return (
                          <li key={optionIndex}>
                            <button
                              type="button"
                              className={`docs-option${chosen ? (correct ? ' is-right' : ' is-wrong') : ''}${
                                revealed[questionIndex] != null && correct ? ' is-right' : ''
                              }`}
                              onClick={() =>
                                setRevealed((current) => ({ ...current, [questionIndex]: optionIndex }))
                              }
                            >
                              {option}
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                    {revealed[questionIndex] != null ? (
                      <p className="docs-quiz-explain">
                        {question.explain}
                        {question.page ? (
                          <button
                            type="button"
                            className="docs-pill"
                            onClick={() => onJumpToPage(question.page)}
                          >
                            p. {question.page}
                          </button>
                        ) : null}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : null}

            {study.kind === 'cards' ? (
              <div className="docs-cards">
                {(study.data.cards || []).map((card, cardIndex) => (
                  <button
                    key={cardIndex}
                    type="button"
                    className={`docs-card${revealed[`card-${cardIndex}`] ? ' is-open' : ''}`}
                    onClick={() =>
                      setRevealed((current) => ({
                        ...current,
                        [`card-${cardIndex}`]: !current[`card-${cardIndex}`],
                      }))
                    }
                  >
                    <strong>{card.term}</strong>
                    <span>
                      {revealed[`card-${cardIndex}`]
                        ? card.definition
                        : 'tap to reveal'}
                    </span>
                    {card.page ? <em>p. {card.page}</em> : null}
                  </button>
                ))}
              </div>
            ) : null}

            {study.kind === 'notes' ? (
              <div className="docs-notes">
                <ReactMarkdown>{study.data.notes || ''}</ReactMarkdown>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="docs-study-bar">
        <button type="button" onClick={() => runStudy('quiz')} disabled={!!studyBusy}>
          {studyBusy === 'quiz' ? <Loader2 size={13} className="docs-spin" /> : <ListChecks size={13} />}
          Quiz
        </button>
        <button type="button" onClick={() => runStudy('cards')} disabled={!!studyBusy}>
          {studyBusy === 'cards' ? <Loader2 size={13} className="docs-spin" /> : <Layers size={13} />}
          Flashcards
        </button>
        <button type="button" onClick={() => runStudy('notes')} disabled={!!studyBusy}>
          {studyBusy === 'notes' ? <Loader2 size={13} className="docs-spin" /> : <BookOpen size={13} />}
          Study guide
        </button>
      </div>

      <form
        className="docs-chat-input"
        onSubmit={(event) => {
          event.preventDefault()
          ask()
        }}
      >
        <input
          type="text"
          value={input}
          placeholder="Ask about a page, a definition, an example…"
          onChange={(event) => setInput(event.target.value)}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()} aria-label="Send">
          <Send size={14} />
        </button>
      </form>
    </section>
  )
}
