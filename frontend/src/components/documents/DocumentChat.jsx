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

/* The backend already normalises citations to inline code, but a model can
   still emit "[p. 2]". Rewriting that here means the marker is a button (and
   jumps the viewer) whatever shape it arrives in. */
function normaliseCitations(text) {
  return String(text || '').replace(/\[\s*(p\.\s*\d{1,4})\s*\]/gi, '`$1`')
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
    return new Promise((resolve) => {
      setMessages((draft) => {
        draft[draft.length - 1] = {
          role: 'assistant',
          content: '',
          loading: false,
          streaming: !!fullAnswer,
          ...extra,
        }
      })

      if (!fullAnswer) {
        resolve()
        return
      }

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
        if (done) {
          window.clearInterval(intervalId)
          resolve()
        }
      }, speed)
    })
  }

  /* The model has a fixed output budget. When it runs out mid-thought the
     backend says so, and the rest is asked for as a plain follow-up turn: the
     answer becomes a second message in the conversation instead of a sentence
     that stops at "## A". */
  const CONTINUE_PROMPT =
    'Continue exactly where you stopped. Do not repeat what you already wrote, ' +
    'do not restart the answer, and do not add an introduction. Keep the same ' +
    'section structure and the same page citations.'

  async function askWithContinuations(question, history) {
    let nextQuestion = question
    let turns = [...history]

    for (let round = 0; round < 3; round += 1) {
      const response = await fetch(`${API_BASE_URL}/api/document/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: nextQuestion, doc_id: doc.doc_id, history: turns }),
      })
      if (!response.ok) throw new Error(`Backend error ${response.status}`)

      const data = await response.json()
      const text = normaliseCitations(data.answer ?? '')
      await revealAnswer(text)

      if (!data.truncated || !text) return

      // A fresh message for the remainder, so the reader sees a clean break
      // rather than one answer that ends mid-sentence.
      setMessages((draft) => {
        draft.push({ role: 'assistant', content: '', loading: true })
      })
      turns = [
        ...turns,
        { role: 'user', content: nextQuestion },
        { role: 'assistant', content: text },
      ].slice(-6)
      nextQuestion = CONTINUE_PROMPT
    }
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
      await askWithContinuations(trimmed, history)
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
      // The quick-action key and the endpoint name are not the same: "cards"
      // is /flashcards. Mapping it explicitly is what keeps the button from
      // 404-ing.
      const endpoint =
        kind === 'quiz' ? 'quiz' : kind === 'cards' ? 'flashcards' : 'notes'

      const response = await fetch(`${API_BASE_URL}/api/document/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: doc.doc_id }),
      })
      if (!response.ok) throw new Error(`Backend error ${response.status}`)
      const data = await response.json()

      let markdown = ''
      if (kind === 'quiz') {
        const questions = data.questions || []
        // The label follows the document's language, so a Greek handout reads
        // "Απάντηση:" like the material it came from.
        const answerLabel = doc?.language === 'Greek' ? 'Απάντηση' : 'Answer'
        const figureLabel = doc?.language === 'Greek' ? 'Σχήματα του εγγράφου' : 'Figures in the document'

        // The figures come first, drawn from the description the ingest pass
        // produced. A question about the tree in Figure 14 is unanswerable while
        // the reader cannot see the tree, and this puts it in front of them
        // before the questions rather than behind a page jump.
        const figuresBlock = (data.figures || []).length
          ? `### ${figureLabel}\n\n${(data.figures || [])
              .map(
                (figure) =>
                  `**p. ${figure.page}**\n\n\`\`\`\n${String(figure.text).slice(0, 1600)}\n\`\`\``,
              )
              .join('\n\n')}\n\n---\n\n`
          : ''

        markdown =
          figuresBlock +
          (questions.length
            ? questions
                .map((question, index) => {
                  // Each option is its own paragraph: a blank line between them
                  // gives the block the air a printed quiz has, and LaTeX inside
                  // still renders through KaTeX.
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

      await revealAnswer(markdown)

      // A study guide is the one study answer long enough to hit the output
      // budget; the remainder is asked for as a follow-up turn, exactly like a
      // long chat answer.
      if (kind === 'notes' && data.truncated && markdown) {
        let turns = [
          { role: 'user', content: label },
          { role: 'assistant', content: markdown },
        ]
        for (let round = 0; round < 2; round += 1) {
          const followUp = await fetch(`${API_BASE_URL}/api/document/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              question: CONTINUE_PROMPT,
              doc_id: doc.doc_id,
              history: turns,
            }),
          })
          if (!followUp.ok) break
          const part = await followUp.json()
          const text = normaliseCitations(part.answer ?? '')
          setMessages((draft) => {
            draft.push({ role: 'assistant', content: '', loading: true })
          })
          await revealAnswer(text)
          if (!part.truncated) break
          turns = [
            ...turns,
            { role: 'user', content: CONTINUE_PROMPT },
            { role: 'assistant', content: text },
          ].slice(-6)
        }
      }
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
