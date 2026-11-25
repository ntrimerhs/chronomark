import { ChevronLeft, ChevronRight, Minus, Plus } from 'lucide-react'

/* The pages panel: a head with the document label, page and zoom controls, and
   the real PDF rendered in the frame.

   There is no thumbnail rail. The prototype drew a strip of fake paper
   thumbnails down the left edge; in a real reader they cost a third of the
   visible page to say what the page counter already says, so the page is left
   to the page. The document name took over the head label, so the file the
   workspace belongs to stays visible after the top bar was removed. */

export default function WorkspaceViewer({ document: doc, page, zoom, onPage, onZoom }) {
  const total = doc.page_count || 1
  const base = (doc.file_url || '').split('#')[0]
  // The page number and zoom live in this panel's head, so the viewer's own
  // toolbar is redundant. Every major browser honours these parameters; a
  // browser that ignores them simply shows its toolbar as before.
  const zoomParam = zoom && zoom !== 100 ? `&zoom=${zoom}` : ''
  const chrome = 'toolbar=0&navpanes=0&statusbar=0&messages=0&view=FitH'

  return (
    <article className="panel document-panel pdf-mode">
      <div className="panel-head">
        <span className="head-label file-chip" title={doc.file_name}>
          {doc.file_name}
        </span>
        <div className="toolset">
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
        <div className="page-scroll">
          {base ? (
            <iframe
              key={`${base}-${page}-${zoom}`}
              className="pdf-frame"
              title={`${doc.file_name} page ${page}`}
              src={`${base}#page=${page}${zoomParam}&${chrome}`}
            />
          ) : (
            <div className="pdf-expired">
              <strong>The uploaded file has been removed</strong>
              <p>
                An upload is kept for three hours, so the bucket does not fill with
                handouts nobody opens again. Nothing else is affected: the page
                texts, the questions and this document&rsquo;s chat history stay
                exactly where they were. Upload the file again to see the pages.
              </p>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}
