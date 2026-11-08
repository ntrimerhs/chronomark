import { memo, createContext, useContext } from 'react';
import Markdown from 'react-markdown';
import useAutoScroll from '../hooks/useAutoScroll';
import { User, Bot, Loader2 } from 'lucide-react';
import { CircleX } from 'lucide-react';
import { API_BASE_URL } from '../config';
import '../styles/chatmessages.css';

const INLINE_TIMESTAMP_RE = /^(\d{1,2}):(\d{2})$/;

function parseTimestampToSeconds(text) {
  const match = INLINE_TIMESTAMP_RE.exec(text.trim());
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
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

// Module scope on purpose. The video fires `timeupdate` about four times a
// second, which re-renders everything above the chat. When this renderer was
// defined inside ChatMessages it got a new function identity on every render,
// react-markdown treated it as a new element type and remounted the <button> --
// so a marker under the cursor lost :hover for a frame and its colour
// transition restarted, which is the white/pink blink. A stable component type
// keeps the same DOM node, and the marker stops blinking.
function MarkdownCode({ children, className }) {
  const onSeek = useContext(SeekContext);
  const text = String(children);
  // A fenced block always carries a language tag: its body is real code.
  const isFenced =
    typeof className === 'string' && className.startsWith('language-');
  const seconds = isFenced ? null : parseTimestampToSeconds(text);

  if (seconds != null) {
    return (
      <button
        type="button"
        className="chat-message-inline-timestamp"
        title={`Jump to ${text.trim()}`}
        onClick={() => {
          reportCitationClick();
          if (onSeek) onSeek(seconds);
        }}
      >
        {text.trim()}
      </button>
    );
  }

  // Only className/children are forwarded on purpose: react-markdown also passes
  // a `node` AST handle, and spreading it leaks node="[object Object]" into the
  // HTML.
  return <code className={className}>{children}</code>;
}

const markdownComponents = { code: MarkdownCode };

function ChatMessages({ messages, isLoading, onSeek }) {
  const scrollContentRef = useAutoScroll(isLoading);

  return (
    <SeekContext.Provider value={onSeek}>
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

          return (
            <div
              key={idx}
              className={`chat-message ${role === 'user' ? 'chat-message-user' : ''}`}
            >
              <div className={`chat-message-avatar ${role === 'user' ? 'chat-message-avatar-user' : 'chat-message-avatar-assistant'}`}>
                {role === 'user' ? <User size={14} /> : <Bot size={14} />}
              </div>

              <div className="chat-message-content">
                <div className="markdown-container">
                  {role === 'assistant' && !streaming ? (
                    <Markdown components={markdownComponents}>{content}</Markdown>
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
              </div>
            </div>
          );
        })}
      </div>
    </SeekContext.Provider>
  );
}

// The chat only changes when a message does; a playing video must not re-render
// (let alone re-parse) every answer four times a second.
export default memo(ChatMessages);
