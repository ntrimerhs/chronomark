import { useState } from 'react'
import { PanelLeft, Plus, Search, Trash2 } from 'lucide-react'

/* Conversations sidebar: the wordmark on top, a collapse control, New chat /
   Search chats, grouped history with delete, and the document this workspace
   belongs to pinned at the bottom.

   The wordmark is the way home. No mark beside it: the workspace header is gone,
   so the one always-visible piece of chrome is the name itself, set in type the
   way the site header sets it. */

function groupFor(timestamp) {
  if (!timestamp) return 'Earlier'
  const days = (Date.now() / 1000 - timestamp) / 86400
  if (days < 1) return 'Today'
  if (days < 7) return 'Previous 7 days'
  return 'Earlier'
}

export default function WorkspaceSidebar({
  chats,
  activeChatId,
  document: doc,
  collapsed,
  open,
  onToggle,
  onNewChat,
  onSelect,
  onDelete,
  onClose,
}) {
  const [searching, setSearching] = useState(false)
  const [query, setQuery] = useState('')

  const visible = chats.filter((chat) =>
    (chat.title || '').toLowerCase().includes(query.trim().toLowerCase()),
  )
  const groups = visible.reduce((result, chat) => {
    const key = groupFor(chat.updated_at)
    result[key] = result[key] || []
    result[key].push(chat)
    return result
  }, {})

  return (
    <>
      <div
        className={`sidebar-backdrop${open ? ' visible' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className={`sidebar${collapsed ? ' collapsed' : ''}${open ? ' mobile-open' : ''}`}>
        <div className="sidebar-top">
          <a href="/" className="sidebar-brand" title="ChronoMark — home">
            <span className="sidebar-copy sidebar-brand-name">ChronoMark</span>
          </a>
          <button
            type="button"
            className="sidebar-icon"
            onClick={onToggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <PanelLeft size={18} />
          </button>
        </div>

        <div className="sidebar-main-actions">
          <button
            type="button"
            className="sidebar-action new-action"
            onClick={onNewChat}
            title="New chat (upload another document)"
          >
            <span className="sidebar-action-icon">
              <Plus size={17} />
            </span>
            <span className="sidebar-copy">New chat</span>
          </button>
          <button
            type="button"
            className="sidebar-action"
            onClick={() => setSearching((value) => !value)}
            title="Search chats"
          >
            <span className="sidebar-action-icon">
              <Search size={17} />
            </span>
            <span className="sidebar-copy">Search chats</span>
          </button>
        </div>

        {searching ? (
          <div className="search-box">
            <Search size={14} />
            <input
              autoFocus
              type="search"
              value={query}
              placeholder="Search conversation history"
              onChange={(event) => setQuery(event.target.value)}
            />
            <button
              type="button"
              className="sidebar-search-close"
              onClick={() => setSearching(false)}
              aria-label="Close search"
            >
              ×
            </button>
          </div>
        ) : null}

        <div className="sidebar-history">
          {visible.length === 0 ? (
            <p className="history-placeholder">
              {query ? 'No conversation matches that.' : 'No conversations yet. Ask something to start one.'}
            </p>
          ) : (
            Object.entries(groups).map(([label, items]) => (
              <div key={label} className="history-group">
                <p className="history-group-title sidebar-copy">{label}</p>
                {items.map((chat) => (
                  <div
                    key={chat.id}
                    className={`history-item${chat.id === activeChatId ? ' active' : ''}`}
                  >
                    <button
                      type="button"
                      className="history-open"
                      onClick={() => onSelect(chat.id)}
                      title={chat.title}
                    >
                      <span className="history-marker" aria-hidden="true" />
                      <span>{chat.title}</span>
                    </button>
                    <button
                      type="button"
                      className="history-delete"
                      onClick={() => onDelete(chat.id)}
                      aria-label={`Delete ${chat.title}`}
                      title="Delete"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>

        {doc ? (
          <div className="sidebar-bottom">
            <p className="sidebar-bottom-label sidebar-copy">Current document</p>
            <div className="sidebar-document">
              <span className="sidebar-document-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <path d="M6 2.5h8l5 5V21H6a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2Z" />
                  <path d="M14 2.5v5h5M8 13h8M8 17h6" />
                </svg>
              </span>
              <span className="sidebar-document-text sidebar-copy">
                <strong>{doc.file_name}</strong>
                <small>
                  {doc.kind?.toUpperCase()} · {doc.page_count} pages
                </small>
              </span>
            </div>
          </div>
        ) : null}
      </aside>
    </>
  )
}
