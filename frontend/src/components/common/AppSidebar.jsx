import { useMemo, useState } from 'react'
import { MoreHorizontal, PanelLeft, Plus, Search } from 'lucide-react'
import '../../styles/documentsReference.css'

/* The one sidebar, for every workspace.

   Its structure is the document workspace's, because that is the one that was
   designed properly: the wordmark on top (it is the way home), a collapse
   control, the actions that start something new, a search that filters the
   list, the history grouped by day, and what this workspace is about pinned at
   the bottom. A document workspace fills the history with conversations, a
   video workspace with the recordings it knows, a workspace list with files --
   the same shape, the same reading rhythm, one component.

   Everything is a prop, nothing is imported from the page that uses it, so a
   change here lands in all three at once instead of in one of them.

   The markup keeps the `sidebar-*` class names and `.docs-app` values on
   purpose: the visual language already lives in documentsReference.css, and
   copying it into a second file only creates a second thing to keep in sync.
   The scope wrapper is `display:contents`, so it provides the tokens without
   adding a box to the page's own flex or grid. */

function groupFor(timestamp) {
  if (!timestamp) return 'Earlier'
  const seconds = typeof timestamp === 'number'
    ? timestamp > 1e12 ? timestamp / 1000 : timestamp
    : Date.parse(timestamp) / 1000
  if (!Number.isFinite(seconds)) return 'Earlier'
  const days = (Date.now() / 1000 - seconds) / 86400
  if (days < 1) return 'Today'
  if (days < 7) return 'Previous 7 days'
  return 'Earlier'
}

const GROUP_ORDER = ['Today', 'Previous 7 days', 'Earlier']

export default function AppSidebar({
  collapsed = false,
  open = false,
  onToggle,
  onClose,
  brandHref = '/',
  brandLabel = 'ChronoMark',
  actions = [],
  search = null,
  items = [],
  activeId = null,
  onSelectItem,
  onDeleteItem,
  onRenameItem = null,
  emptyText = 'Nothing here yet.',
  children = null,
  footerLabel = '',
  footerIcon = null,
  footerTitle = '',
  footerMeta = '',
  footerNote = '',
  footer = null,
  footerAction = null,
}) {
  const [searching, setSearching] = useState(false)
  const [query, setQuery] = useState('')
  // The name of a conversation is the reader's to change: one double click puts
  // it in a field, Enter keeps it, Escape forgets it.
  const [editingId, setEditingId] = useState(null)
  const [draftTitle, setDraftTitle] = useState('')

  const startRename = (item) => {
    if (!onRenameItem || item.renamable === false) return
    setEditingId(item.id)
    setDraftTitle(item.title || '')
  }

  const commitRename = () => {
    const value = draftTitle.trim()
    if (editingId && value) onRenameItem?.(editingId, value)
    setEditingId(null)
    setDraftTitle('')
  }

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return items
    return items.filter((item) => String(item.title || '').toLowerCase().includes(needle))
  }, [items, query])

  const groups = useMemo(() => {
    const buckets = new Map()
    visible.forEach((item) => {
      // An item may name its own group ("Library"); everything else falls back
      // to the day it was last touched.
      const key = item.group || groupFor(item.updated_at)
      if (!buckets.has(key)) buckets.set(key, [])
      buckets.get(key).push(item)
    })
    const named = [...buckets.keys()].filter((key) => !GROUP_ORDER.includes(key))
    return [...named, ...GROUP_ORDER.filter((key) => buckets.has(key))].map((key) => [
      key,
      buckets.get(key),
    ])
  }, [visible])

  const showFooter = Boolean(footer || footerTitle || footerNote)

  return (
    <div className="docs-app dark side-scope" style={{ display: 'contents' }}>
      <div
        className={`sidebar-backdrop${open ? ' visible' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside className={`sidebar${collapsed ? ' collapsed' : ''}${open ? ' mobile-open' : ''}`}>
        <div className="sidebar-top">
          <a href={brandHref} className="sidebar-brand" title={`${brandLabel} — home`}>
            <span className="sidebar-copy sidebar-brand-name">{brandLabel}</span>
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
          {actions.map((action) => {
            const Icon = action.icon || Plus
            return (
              <button
                key={action.key || action.label}
                type="button"
                className={`sidebar-action${action.primary ? ' new-action' : ''}`}
                onClick={action.onClick}
                disabled={action.disabled}
                title={action.title || action.label}
              >
                <span className="sidebar-action-icon">
                  <Icon size={action.iconSize || 17} />
                </span>
                <span className="sidebar-copy">{action.label}</span>
              </button>
            )
          })}

          {search ? (
            <button
              type="button"
              className="sidebar-action"
              onClick={() => setSearching((value) => !value)}
              title="Search"
            >
              <span className="sidebar-action-icon">
                <Search size={17} />
              </span>
              <span className="sidebar-copy">{search.label || 'Search'}</span>
            </button>
          ) : null}
        </div>

        {search && searching ? (
          <div className="search-box">
            <Search size={14} />
            <input
              autoFocus
              type="search"
              value={query}
              placeholder={search.placeholder || 'Search'}
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

        {children ? <div className="sidebar-custom sidebar-copy">{children}</div> : null}

        <div className="sidebar-history">
          {visible.length === 0 ? (
            <p className="history-placeholder">
              {query ? 'Nothing matches that search.' : emptyText}
            </p>
          ) : (
            groups.map(([label, entries]) => (
              <div key={label} className="history-group">
                <p className="history-group-title sidebar-copy">{label}</p>
                {entries.map((item) => {
                  const ItemIcon = item.icon || null
                  return (
                    <div
                      key={item.id}
                      className={`history-item${item.id === activeId || item.active ? ' active' : ''}`}
                    >
                      {editingId === item.id ? (
                        <input
                          className="history-rename"
                          value={draftTitle}
                          autoFocus
                          aria-label={`Rename ${item.title}`}
                          onChange={(event) => setDraftTitle(event.target.value)}
                          onBlur={commitRename}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                              event.preventDefault()
                              commitRename()
                            } else if (event.key === 'Escape') {
                              event.preventDefault()
                              setEditingId(null)
                              setDraftTitle('')
                            }
                          }}
                        />
                      ) : (
                        <button
                          type="button"
                          className="history-open"
                          onClick={() => onSelectItem?.(item.id)}
                          onDoubleClick={() => startRename(item)}
                          title={
                            onRenameItem && item.renamable !== false
                              ? `${item.title} — double-click to rename`
                              : item.title
                          }
                        >
                          {ItemIcon ? (
                            <ItemIcon size={14} />
                          ) : (
                            <span className="history-marker" aria-hidden="true" />
                          )}
                          <span>{item.title}</span>
                        </button>
                      )}
                      {onDeleteItem && item.deletable !== false ? (
                        <button
                          type="button"
                          className="history-delete"
                          onClick={() => onDeleteItem(item.id)}
                          aria-label={`Delete ${item.title}`}
                          title="Delete"
                        >
                          <MoreHorizontal size={14} />
                        </button>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            ))
          )}
        </div>

        {showFooter ? (
          <div className="sidebar-bottom">
            {footer || (
              <>
                {footerLabel ? (
                  <p className="sidebar-bottom-label sidebar-copy">{footerLabel}</p>
                ) : null}
                <div className="sidebar-document">
                  {footerIcon ? (
                    <span className="sidebar-document-icon" aria-hidden="true">
                      {footerIcon}
                    </span>
                  ) : null}
                  <span className="sidebar-document-text sidebar-copy">
                    <strong title={footerTitle}>{footerTitle}</strong>
                    {footerMeta ? <small>{footerMeta}</small> : null}
                  </span>
                  {footerAction ? <span className="doc-status" aria-hidden="true" /> : null}
                </div>
                {footerNote ? (
                  <p className="sidebar-bottom-note sidebar-copy">{footerNote}</p>
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </aside>
    </div>
  )
}
