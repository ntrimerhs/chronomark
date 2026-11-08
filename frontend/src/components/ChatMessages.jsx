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

function ChatMessages({ messages, isLoading, onSeek }) {
  const scrollContentRef = useAutoScroll(isLoading);

  // The LLM is instructed to write a bare `mm:ss` marker right above every code
  // snippet or example it produces. Intercept that inline code and render it as
  // clickable text in place, so each jump-to time stays attached to the section
  // it belongs to instead of being collected into a separate row of pills under
  // the answer.
  const markdownComponents = {
    // Only className/children are forwarded on purpose: react-markdown also
    // passes a `node` AST handle, and spreading it onto the DOM tag leaks an
    // invalid node="[object Object]" attribute into the HTML.
    code({ children, className }) {
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

      return <code className={className}>{children}</code>;
    },
  };

  return (
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
  );
}

export default ChatMessages;
