import { useState } from 'react'
import {
  ChevronLeft,
  FileText,
  MessageSquarePlus,
  PanelLeft,
  Search,
  Trash2,
} from 'lucide-react'

/* Conversation sidebar, ChatGPT-shaped.

   A document keeps every conversation it has had: new chat, search, the list
   grouped by recency, delete, and the document it all belongs to pinned at the
   bottom. Collapsing it hands the width back to the pages and the chat, which is
   the whole reason it can collapse. */

function groupFor(timestamp) {
  if (!timestamp) return 'Earlier'
  const days = (Date.now() / 1000 - timestamp) / 86400
  if (days < 1) return 'Today'
  if (days < 7) return 'Previous 7 days'
  return 'Earlier'
}

export default function DocumentsSidebar({
  chats,
  activeChatId,
  document: doc,
  collapsed,
  onToggle,
  onNewChat,
  onSelect,
  onDelete,
}) {
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)

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
    <aside className={`docs-sidebar${collapsed ? ' is-collapsed' : ''}`}>
      <div className="docs-sidebar-top">
        {!collapsed ? (
          <span className="docs-sidebar-title">
            <span className="docs-sidebar-mark">⌘</span>
            Chats
          </span>
        ) : null}
        <button
          type="button"
          className="docs-icon-btn"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand the sidebar' : 'Collapse the sidebar'}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          {collapsed ? <PanelLeft size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>

      <div className="docs-sidebar-actions">
        <button type="button" className="docs-sidebar-action is-new" onClick={onNewChat}>
          <MessageSquarePlus size={16} />
          {!collapsed ? <span>New chat</span> : null}
        </button>
        <button
          type="button"
          className="docs-sidebar-action"
          onClick={() => setSearching((value) => !value)}
        >
          <Search size={16} />
          {!collapsed ? <span>Search chats</span> : null}
        </button>
      </div>

      {searching && !collapsed ? (
        <div className="docs-sidebar-search">
          <Search size={13} />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search conversations…"
          />
        </div>
      ) : null}

      <div className="docs-sidebar-history">
        {visible.length === 0 ? (
          <p className="docs-sidebar-empty">
            {query ? 'No conversation matches that.' : 'No conversations yet. Ask something to start one.'}
          </p>
        ) : (
          Object.entries(groups).map(([label, items]) => (
            <div key={label} className="docs-history-group">
              {!collapsed ? <p className="docs-history-title">{label}</p> : null}
              {items.map((chat) => (
                <div
                  key={chat.id}
                  className={`docs-history-item${chat.id === activeChatId ? ' is-active' : ''}`}
                >
                  <button
                    type="button"
                    className="docs-history-open"
                    onClick={() => onSelect(chat.id)}
                    title={chat.title}
                  >
                    <Line />
                    {!collapsed ? <span>{chat.title}</span> : null}
                  </button>
                  {!collapsed ? (
                    <button
                      type="button"
                      className="docs-history-delete"
                      onClick={() => onDelete(chat.id)}
                      aria-label={`Delete ${chat.title}`}
                    >
                      <Trash2 size={13} />
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          ))
        )}
      </div>

      {doc ? (
        <div className="docs-sidebar-doc">
          <span className="docs-sidebar-doc-icon">
            <FileText size={15} />
          </span>
          {!collapsed ? (
            <span className="docs-sidebar-doc-text">
              <strong>{doc.file_name}</strong>
              <small>
                {doc.kind?.toUpperCase()} · {doc.page_count} pages
              </small>
            </span>
          ) : null}
        </div>
      ) : null}
    </aside>
  )
}

function Line() {
  return <span className="docs-history-dot" aria-hidden="true" />
}
