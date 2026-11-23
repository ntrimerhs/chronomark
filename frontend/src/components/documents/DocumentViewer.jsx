import { forwardRef, useEffect, useRef, useImperativeHandle, useState } from 'react'

/* The document viewer.

   PDFs are handed to the browser's own viewer in an iframe: Chrome, Edge and
   Firefox all render them natively, including selection and search, without a
   worker bundle or a CORS policy. Page and zoom travel in the URL fragment, and
   the frame is keyed by both, so a citation jump reliably lands on the page
   instead of relying on the fragment changing inside a loaded document.

   PowerPoint and Word cannot be rendered by a browser at all, so their extracted
   page text is shown instead, in the same paged frame, so a `p. N` citation still
   lands on the exact slide. */

function PdfFrame({ fileUrl, page, zoom }, ref) {
  const [loaded, setLoaded] = useState(false)
  const base = fileUrl.split('#')[0]

  useImperativeHandle(ref, () => ({ scrollToPage() {} }), [])

  useEffect(() => {
    // The load event is not guaranteed once the built-in viewer takes over the
    // frame, and a "Loading" label stuck over a rendered page is worse than none.
    setLoaded(false)
    const guard = window.setTimeout(() => setLoaded(true), 4000)
    return () => window.clearTimeout(guard)
  }, [page, zoom, base])

  return (
    <div className="docs-frame-wrap">
      {!loaded ? <p className="docs-viewer-loading">Loading pages…</p> : null}
      <iframe
        key={`${base}-${page}-${zoom}`}
        className="docs-pdf-frame"
        title={`Document page ${page}`}
        // The browser's own viewer stays visible on purpose: hiding its toolbar
        // also removes the thumbnail rail, which is the fastest way to move
        // through a 40-page handout.
        src={`${base}#page=${page}&zoom=${zoom}`}
        onLoad={() => setLoaded(true)}
      />
    </div>
  )
}

const PdfFrameWithRef = forwardRef(PdfFrame)

function TextViewer({ pages, pageHint }, ref) {
  const scrollRef = useRef(null)
  const [highlight, setHighlight] = useState(null)

  useImperativeHandle(
    ref,
    () => ({
      scrollToPage(nextPage) {
        setHighlight(nextPage)
        const container = scrollRef.current
        if (!container) return
        const target = container.querySelector(`[data-page="${nextPage}"]`)
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      },
    }),
    [],
  )

  useEffect(() => {
    if (pageHint) setHighlight(pageHint)
  }, [pageHint])

  return (
    <div className="docs-text-scroll" ref={scrollRef}>
      {pages.map((page) => (
        <article
          key={page.page}
          className={`docs-text-page${highlight === page.page ? ' is-cited' : ''}`}
          data-page={page.page}
        >
          <header>
            <span>{page.heading || 'page'}</span>
            <strong>p. {page.page}</strong>
          </header>
          {page.text
            .split(/\n{2,}/)
            .filter(
              (paragraph) =>
                paragraph.trim().toLowerCase() !== (page.heading || '').trim().toLowerCase(),
            )
            .map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
        </article>
      ))}
    </div>
  )
}

const TextViewerWithRef = forwardRef(TextViewer)

export default function DocumentViewer({
  document: doc,
  page = 1,
  zoom = 100,
  mode = 'pdf',
  viewerRef,
}) {
  if (!doc) return null

  const wantsPages = mode !== 'text' && doc.kind === 'pdf' && doc.file_url

  if (wantsPages) {
    return <PdfFrameWithRef ref={viewerRef} fileUrl={doc.file_url} page={page} zoom={zoom} />
  }

  return <TextViewerWithRef ref={viewerRef} pages={doc.pages || []} pageHint={page} />
}
