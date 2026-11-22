import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'

/* The document viewer.

   PDFs are handed to the browser's own PDF viewer in an <iframe>: Chrome, Edge
   and Firefox all render PDFs natively, including zoom, text selection and
   search, and they do it without a worker bundle or a CORS policy. A page jump
   is just the `#page=N` fragment, re-set on the same URL.

   PPTX and DOCX cannot be rendered by a browser at all, so their extracted page
   text is shown instead, in the same paged frame, so a `p. N` citation still
   lands on the exact slide. */

function PdfFrame({ fileUrl, pageHint }, ref) {
  const frameRef = useRef(null)
  const [loaded, setLoaded] = useState(false)

  const goTo = (page) => {
    const frame = frameRef.current
    if (!frame) return
    const base = fileUrl.split('#')[0]
    // Keeping the document loaded while only the fragment changes avoids a
    // full re-fetch on every citation click.
    frame.src = `${base}#page=${page}&zoom=page-width`
  }

  useImperativeHandle(ref, () => ({ scrollToPage: goTo }), [fileUrl])

  useEffect(() => {
    if (!pageHint) return
    goTo(pageHint)
  }, [pageHint, fileUrl])

  return (
    <div className="docs-frame-wrap">
      {!loaded ? <p className="docs-viewer-loading">Loading pages…</p> : null}
      <iframe
        ref={frameRef}
        className="docs-pdf-frame"
        title="Document pages"
        src={`${fileUrl}#page=1&zoom=page-width`}
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
      scrollToPage(page) {
        setHighlight(page)
        const container = scrollRef.current
        if (!container) return
        const target = container.querySelector(`[data-page="${page}"]`)
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
            // The extractor's heading is already the frame's title; printing it
            // twice reads like a bug.
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

export default function DocumentViewer({ document: doc, pageHint, viewerRef }) {
  if (!doc) return null

  if (doc.kind === 'pdf' && doc.file_url) {
    return <PdfFrameWithRef ref={viewerRef} fileUrl={doc.file_url} pageHint={pageHint} />
  }

  return <TextViewerWithRef ref={viewerRef} pages={doc.pages || []} pageHint={pageHint} />
}
