import { ChevronLeft, ChevronRight, LayoutPanelLeft, Minus, Plus } from 'lucide-react'

/* The pages panel, built to the reference: a panel head with thumbnail, page and
   zoom controls, a thumbnail rail, and the real PDF rendered in the frame.

   The rail shows the pages around the current one. The prototype drew fake paper
   thumbnails; here the number is real and clicking it is a real jump. */

export default function WorkspaceViewer({
  document: doc,
  page,
  zoom,
  onPage,
  onZoom,
  showThumbs,
  onToggleThumbs,
}) {
  const total = doc.page_count || 1
  const base = (doc.file_url || '').split('#')[0]
  // The page number, zoom and thumbnails already live in this panel's head, so
  // the viewer's own toolbar is redundant. Every major browser honours these
  // parameters; a browser that ignores them simply shows its toolbar as before.
  const zoomParam = zoom && zoom !== 100 ? `&zoom=${zoom}` : ''
  const chrome = 'toolbar=0&navpanes=0&statusbar=0&messages=0&view=FitH'

  const visible = []
  for (let offset = -2; offset <= 2; offset += 1) {
    const candidate = page + offset
    if (candidate >= 1 && candidate <= total) visible.push(candidate)
  }

  return (
    <article className="panel document-panel pdf-mode">
      <div className="panel-head">
        <span className="head-label">Document viewer</span>
        <div className="toolset">
          <button
            type="button"
            className={`icon-btn${showThumbs ? ' on' : ''}`}
            title="Show or hide thumbnails"
            onClick={onToggleThumbs}
            aria-pressed={showThumbs}
          >
            <LayoutPanelLeft size={15} />
          </button>
          <div className="divider" />
          <button
            type="button"
            className="icon-btn"
            title="Previous page"
            onClick={() => onPage(page - 1)}
            disabled={page <= 1}
          >
            <ChevronLeft size={15} />
          </button>
          <div className="pagecount">
            <input
              className="pagefield"
              type="number"
              min="1"
              max={total}
              value={page}
              aria-label="Page number"
              onChange={(event) => {
                const value = Number(event.target.value)
                if (value >= 1 && value <= total) onPage(value)
              }}
            />
            <em>/ {total}</em>
          </div>
          <button
            type="button"
            className="icon-btn"
            title="Next page"
            onClick={() => onPage(page + 1)}
            disabled={page >= total}
          >
            <ChevronRight size={15} />
          </button>
          <div className="divider" />
          <button type="button" className="icon-btn" title="Zoom out" onClick={() => onZoom(-1)}>
            <Minus size={15} />
          </button>
          <span className="zoom">{zoom}%</span>
          <button type="button" className="icon-btn" title="Zoom in" onClick={() => onZoom(1)}>
            <Plus size={15} />
          </button>
        </div>
      </div>

      <div className="viewer">
        <aside className={`thumbs${showThumbs ? '' : ' hide'}`}>
          {visible.map((number) => (
            <button
              type="button"
              key={number}
              className={`thumb${number === page ? ' selected' : ''}`}
              onClick={() => onPage(number)}
            >
              <span className="thumb-paper">
                <span className="thumb-number">{number}</span>
                <span className="tiny-line m" />
                <span className="tiny-line" />
                <span className="tiny-line s" />
              </span>
              <span>{number}</span>
            </button>
          ))}
        </aside>

        <div className="page-scroll">
          <iframe
            key={`${base}-${page}-${zoom}`}
            className="pdf-frame"
            title={`${doc.file_name} page ${page}`}
            src={`${base}#page=${page}${zoomParam}&${chrome}`}
          />
        </div>
      </div>
    </article>
  )
}
