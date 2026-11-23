import { memo, createContext, useContext, useState } from 'react';
import Markdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import useAutoScroll from '../hooks/useAutoScroll';
import { User, Bot, Loader2, ThumbsDown, ThumbsUp, Wand2 } from 'lucide-react';
import { CircleX } from 'lucide-react';
import { API_BASE_URL } from '../config';
import '../styles/chatmessages.css';

const INLINE_TIMESTAMP_RE = /^(\d{1,2}):(\d{2})$/;
// Documents cite pages instead of moments: `p. 12`. Same inline-code shape, so
// the same marker component handles both.
const INLINE_PAGE_RE = /^[\[(]?\s*p\.\s*(\d{1,4})\s*[\])]?$/i;

function parseTimestampToSeconds(text) {
  const match = INLINE_TIMESTAMP_RE.exec(text.trim());
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

function parsePageCitation(text) {
  const match = INLINE_PAGE_RE.exec(text.trim());
  if (!match) return null;
  return Number(match[1]);
}

// Fire-and-forget: a citation click is the only signal that says the jump link
// is actually used, but telemetry must never delay or break the seek itself.
function reportCitationClick() {
  try {
    fetch(`${API_BASE_URL}/metrics/citation-click`, {
      method: 'POST',
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* the seek still has to happen */
  }
}

const SeekContext = createContext(null);
// Documents label a page citation in their own language ("Σελίδα 8", "Page 8")
// and render it as a pill with an icon instead of bare inline code.
const CitationLabelContext = createContext(null);
// A follow-up hook lets the document chat offer "explain this" under an answer.
const FollowUpContext = createContext(null);

// Module scope on purpose. The video fires `timeupdate` about four times a
// second, which re-renders everything above the chat. When this renderer was
// defined inside ChatMessages it got a new function identity on every render,
// react-markdown treated it as a new element type and remounted the <button> --
// so a marker under the cursor lost :hover for a frame and its colour
// transition restarted, which is the white/pink blink. A stable component type
// keeps the same DOM node, and the marker stops blinking.
function MarkdownCode({ children, className }) {
  const onSeek = useContext(SeekContext);
  const citeLabel = useContext(CitationLabelContext);
  const text = String(children);
  // A fenced block always carries a language tag: its body is real code.
  const isFenced =
    typeof className === 'string' && className.startsWith('language-');
  const seconds = isFenced ? null : parseTimestampToSeconds(text);
  const page = isFenced ? null : parsePageCitation(text);

  if (page != null && citeLabel) {
    return (
      <button
        type="button"
        className="chat-page-citation"
        title={citeLabel(page)}
        onClick={() => {
          reportCitationClick();
          if (onSeek) onSeek(page);
        }}
      >
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M4 2.5h5L12.5 6v7.5h-8.5V2.5Z"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
          <path d="M9 2.5V6h3.5" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        </svg>
        {citeLabel(page)}
      </button>
    );
  }

  if (seconds != null || page != null) {
    const label = text.trim();
    return (
      <button
        type="button"
        className="chat-message-inline-timestamp"
        title={page != null ? `Go to page ${page}` : `Jump to ${label}`}
        onClick={() => {
          reportCitationClick();
          if (onSeek) onSeek(page != null ? page : seconds);
        }}
      >
        {label}
      </button>
    );
  }

  // Only className/children are forwarded on purpose: react-markdown also passes
  // a `node` AST handle, and spreading it leaks node="[object Object]" into the
  // HTML.
  return <code className={className}>{children}</code>;
}

const markdownComponents = { code: MarkdownCode };

// Math is written by the model as LaTeX ($...$ inline, $$...$$ display) and
// rendered with KaTeX, so O(n^2) arrives as real notation instead of a caret.
const remarkPlugins = [remarkMath];
const rehypePlugins = [rehypeKatex];

/* The row under an answer: was this useful, and can it be explained again in
   simpler words. Both act on the real conversation, no decorative buttons. */
function AnswerActions({ content, label }) {
  const followUp = useContext(FollowUpContext);
  const [vote, setVote] = useState(null);

  if (!followUp) return null;

  return (
    <div className="chat-answer-actions">
      <button
        type="button"
        className={`chat-action-btn${vote === 'up' ? ' is-on' : ''}`}
        onClick={() => setVote((current) => (current === 'up' ? null : 'up'))}
        aria-label={label('good')}
        title={label('good')}
      >
        <ThumbsUp size={13} />
      </button>
      <button
        type="button"
        className={`chat-action-btn${vote === 'down' ? ' is-on' : ''}`}
        onClick={() => setVote((current) => (current === 'down' ? null : 'down'))}
        aria-label={label('bad')}
        title={label('bad')}
      >
        <ThumbsDown size={13} />
      </button>
      <button
        type="button"
        className="chat-action-btn is-wide"
        onClick={() =>
          followUp(
            'Explain that again more simply, with one small concrete example, and keep the page citations.',
          )
        }
      >
        <Wand2 size={13} />
        {label('explain')}
      </button>
      {content ? null : null}
    </div>
  );
}

function ChatMessages({ messages, isLoading, onSeek, citationLabel, onFollowUp, actionLabel }) {
  const scrollContentRef = useAutoScroll(isLoading);

  return (
    <SeekContext.Provider value={onSeek}>
      <CitationLabelContext.Provider value={citationLabel || null}>
        <FollowUpContext.Provider value={onFollowUp || null}>
          <div ref={scrollContentRef} className="chat-messages">
            {messages.map(({ role, content, loading, error, streaming }, idx) => {
              if (loading && !content) {
                return (
                  <div key={idx} className="chat-message chat-message-thinking">
                    <div className="chat-message-avatar chat-message-avatar-assistant">
                      <Bot size={14} />
                    </div>
                    <div className="chat-message-thinking-bubble">
                      <Loader2 className="chat-message-thinking-spinner" size={14} />
                      <span>Thinking…</span>
                    </div>
                  </div>
                );
              }

              const showActions =
                role === 'assistant' && !loading && !streaming && !error && content;

              return (
                <div
                  key={idx}
                  className={`chat-message ${role === 'user' ? 'chat-message-user' : ''}`}
                >
                  <div className={`chat-message-avatar ${role === 'user' ? 'chat-message-avatar-user' : 'chat-message-avatar-assistant'}`}>
                    {role === 'user' ? <User size={14} /> : <Bot size={14} />}
                  </div>

                  <div className="chat-message-content">
                    {role === 'assistant' ? (
                      <p className="chat-message-author">Chronomark</p>
                    ) : null}

                    <div className="markdown-container">
                      {role === 'assistant' && !streaming ? (
                        <Markdown
                          remarkPlugins={remarkPlugins}
                          rehypePlugins={rehypePlugins}
                          components={markdownComponents}
                        >
                          {content}
                        </Markdown>
                      ) : (
                        <div className="chat-message-text">{content}</div>
                      )}
                    </div>

                    {error && (
                      <div
                        className={`chat-message-error ${content ? 'chat-message-error-with-margin' : ''}`}
                      >
                        <CircleX className="chat-message-error-icon"/>
                        <span>Error generating the response</span>
                      </div>
                    )}

                    {showActions ? (
                      <AnswerActions
                        content={content}
                        label={(kind) => {
                          if (actionLabel) return actionLabel(kind);
                          return kind === 'explain' ? 'Explain this' : kind === 'good' ? 'Good answer' : 'Poor answer';
                        }}
                      />
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </FollowUpContext.Provider>
      </CitationLabelContext.Provider>
    </SeekContext.Provider>
  );
}

// The chat only changes when a message does; a playing video must not re-render
// (let alone re-parse) every answer four times a second.
export default memo(ChatMessages);
