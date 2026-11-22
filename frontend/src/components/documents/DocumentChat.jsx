import { useEffect, useState } from 'react'
import { useImmer } from 'use-immer'
import { Bot } from 'lucide-react'
import ChatMessages from '../ChatMessages'
import ChatInput from '../ChatInput'
import { API_BASE_URL } from '../../config'
import '../../styles/chatbot.css'
import '../../styles/chatTheme.css'

/* The document chat.

   Same component, same skin, same conversation behaviour as the video chat --
   the shell here is deliberately identical (`.chatbot`, header, quick actions,
   ChatInput, ChatMessages) so the two pages are one product. Only two things
   differ: the endpoint answers with pages instead of timestamps, and the quick
   actions also cover the study tools, which read the same index. */

const QUICK_ACTIONS = [
  { key: 'summary', label: 'Summarize this document', prompt: 'Summarize this document' },
  { key: 'quiz', label: 'Practice questions' },
  { key: 'cards', label: 'Flashcards' },
  { key: 'notes', label: 'Study guide' },
]

function isGreek(text) {
  return /[\u0370-\u03ff\u1f00-\u1fff]/.test(String(text || ''))
}

function DocumentChat({ document: doc, onJumpToPage }) {
  const [messages, setMessages] = useImmer([])
  const [newMessage, setNewMessage] = useState('')
  const [busyTool, setBusyTool] = useState('')

  // A conversation belongs to one document; switching documents must not send
  // the previous Q&A as history.
  useEffect(() => {
    setMessages(() => [])
    setNewMessage('')
    setBusyTool('')
  }, [doc?.doc_id, setMessages])

  const isLoading =
    messages.length > 0 && messages[messages.length - 1].loading

  function revealAnswer(fullAnswer, extra = {}) {
    setMessages((draft) => {
      draft[draft.length - 1] = {
        role: 'assistant',
        content: '',
        loading: false,
        streaming: !!fullAnswer,
        ...extra,
      }
    })

    if (!fullAnswer) return

    // Chunked reveal, same reasoning as the video chat: one char per tick
    // re-parses markdown hundreds of times a second.
    const totalSteps = Math.min(fullAnswer.length, 60)
    const stepSize = Math.max(1, Math.ceil(fullAnswer.length / totalSteps))
    const speed = Math.max(20, Math.min(40, 1200 / totalSteps))
    let index = 0

    const intervalId = window.setInterval(() => {
      index += stepSize
      const done = index >= fullAnswer.length
      setMessages((draft) => {
        if (draft[draft.length - 1]?.role === 'assistant') {
          draft[draft.length - 1] = {
            ...draft[draft.length - 1],
            content: fullAnswer.slice(0, Math.min(index, fullAnswer.length)),
            streaming: !done,
          }
        }
      })
      if (done) window.clearInterval(intervalId)
    }, speed)
  }

  function pushUserAndPlaceholder(text) {
    setMessages((draft) => {
      draft.push({ role: 'user', content: text })
      draft.push({ role: 'assistant', content: '', loading: true })
    })
  }

  function failWith(message) {
    setMessages((draft) => {
      draft[draft.length - 1] = {
        role: 'assistant',
        content: message || 'Something went wrong.',
        loading: false,
        error: true,
      }
    })
  }

  async function submitNewMessage(overrideText) {
    const trimmed = (overrideText ?? newMessage).trim()
    if (!trimmed || isLoading || !doc) return

    const history = messages
      .filter((message) => !message.loading && !message.error && message.content)
      .map((message) => ({ role: message.role, content: message.content }))
      .slice(-6)

    pushUserAndPlaceholder(trimmed)
    setNewMessage('')

    try {
      const response = await fetch(`${API_BASE_URL}/api/document/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed, doc_id: doc.doc_id, history }),
      })
      if (!response.ok) throw new Error(`Backend error ${response.status}`)
      const data = await response.json()
      revealAnswer(data.answer ?? '')
    } catch (error) {
      console.error(error)
      failWith()
    }
  }

  async function runStudy(kind) {
    if (!doc || isLoading || busyTool) return
    setBusyTool(kind)

    const label =
      kind === 'quiz'
        ? 'Make practice questions'
        : kind === 'cards'
          ? 'Make flashcards'
          : 'Write a study guide'

    pushUserAndPlaceholder(label)

    try {
      const response = await fetch(`${API_BASE_URL}/api/document/${kind}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: doc.doc_id }),
      })
      if (!response.ok) throw new Error(`Backend error ${response.status}`)
      const data = await response.json()

      let markdown = ''
      if (kind === 'quiz') {
        const questions = data.questions || []
        markdown = questions.length
          ? questions
              .map((question, index) => {
                const options = question.options
                  .map((option, optionIndex) => `${'ABCD'[optionIndex]}. ${option}`)
                  .join('\n')
                const answer = `**Answer: ${'ABCD'[question.answer]}**${
                  question.page ? ` (\`p. ${question.page}\`)` : ''
                }${question.explain ? ` — ${question.explain}` : ''}`
                return `### ${index + 1}. ${question.question}\n\n${options}\n\n${answer}`
              })
              .join('\n\n')
          : 'No questions could be built from this document.'
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

      revealAnswer(markdown)
    } catch (error) {
      console.error(error)
      failWith('Could not build the study material.')
    } finally {
      setBusyTool('')
    }
  }

  const isEmpty = messages.length === 0

  return (
    <div className={`chatbot ${isEmpty ? 'chatbot-empty' : 'chatbot-live'}`}>
      <div className="chatbot-header">
        <div className="chatbot-header-icon">
          <Bot size={18} />
        </div>
        <div>
          <p className="chatbot-header-title">ChronoMark</p>
          <div className="chatbot-header-status">
            <span className="chatbot-header-dot" />
            <span>Ready to chat</span>
          </div>
        </div>
      </div>

      {!isEmpty && (
        <ChatMessages messages={messages} isLoading={isLoading} onSeek={onJumpToPage} />
      )}

      {/* Always visible, on purpose: the suggestions are how the student moves
          between asking, practising and revising, so answering one of them must
          not take the others away. */}
      <div className="chatbot-quick-actions" aria-label="Quick actions">
        {QUICK_ACTIONS.map(({ key, label, prompt }) => (
          <button
            key={key}
            type="button"
            className="chatbot-quick-action"
            onClick={() => (prompt ? submitNewMessage(prompt) : runStudy(key))}
            disabled={isLoading || !!busyTool}
          >
            <span>{busyTool === key ? `${label}…` : label}</span>
          </button>
        ))}
      </div>

      {isEmpty && <div className="chatbot-empty-spacer" />}

      <ChatInput
        newMessage={newMessage}
        isLoading={isLoading}
        setNewMessage={setNewMessage}
        submitNewMessage={() => submitNewMessage()}
      />
    </div>
  )
}

export default DocumentChat
