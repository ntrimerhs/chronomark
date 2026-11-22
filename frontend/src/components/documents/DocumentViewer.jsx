import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

/* The document viewer.

   Two shapes, one scroll-to-page contract:
   - PDF: real pages rendered to canvas through pdf.js, so the handout looks the
     way its author laid it out.
   - PPTX/DOCX: the browser cannot render those, so the extracted page text is
     shown instead, in the same paged frame. Honest, and it still lets a
     citation land on the exact slide.

   Pages are rendered lazily, only when they scroll near the viewport: a 200-page
   PDF would otherwise render 200 canvases on open. */

const PAGE_WIDTH = 760

function PdfViewer({ fileUrl, pageHint }, ref) {
  const scrollRef = useRef(null)
  const [doc, setDoc] = useState(null)
  const [error, setError] = useState('')
  const [visible, setVisible] = useState(() => new Set([1]))
  const canvases = useRef(new Map())
  const renderTasks = useRef(new Map())

  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setError('')
    const task = pdfjsLib.getDocument({ url: fileUrl, withCredentials: false })
    task.promise
      .then((loaded) => {
        if (cancelled) return
        setDoc(loaded)
      })
      .catch((loadError) => {
        if (cancelled) return
        console.error('[Docs] PDF load failed', loadError)
        setError('Could not load this PDF. It may have been removed.')
      })
    return () => {
      cancelled = true
      task.destroy?.()
    }
  }, [fileUrl])

  // Render a page only once it is within a screen of the viewport.
  useEffect(() => {
    if (!doc) return undefined
    const container = scrollRef.current
    if (!container) return undefined

    const io = new IntersectionObserver(
      (entries) => {
        setVisible((current) => {
          const next = new Set(current)
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              next.add(Number(entry.target.dataset.page))
            }
          })
          return next.size === current.size ? current : next
        })
      },
      { root: container, rootMargin: '600px 0px' },
    )

    container.querySelectorAll('[data-page]').forEach((node) => io.observe(node))
    return () => io.disconnect()
  }, [doc])

  useEffect(() => {
    if (!doc) return
    visible.forEach((pageNumber) => {
      if (pageNumber < 1 || pageNumber > doc.numPages) return
      if (canvases.current.get(pageNumber)?.dataset.rendered === 'true') return
      if (renderTasks.current.has(pageNumber)) return

      const task = doc
        .getPage(pageNumber)
        .then((page) => {
          const canvas = canvases.current.get(pageNumber)
          if (!canvas) return
          const scale = PAGE_WIDTH / page.getViewport({ scale: 1 }).width
          const viewport = page.getViewport({ scale })
          const ratio = Math.min(window.devicePixelRatio || 1, 2)
          canvas.width = Math.floor(viewport.width * ratio)
          canvas.height = Math.floor(viewport.height * ratio)
          canvas.style.width = `${Math.floor(viewport.width)}px`
          canvas.style.height = `${Math.floor(viewport.height)}px`
          const context = canvas.getContext('2d')
          context.setTransform(ratio, 0, 0, ratio, 0, 0)
          return page.render({ canvasContext: context, viewport }).promise
        })
        .then(() => {
          const canvas = canvases.current.get(pageNumber)
          if (canvas) canvas.dataset.rendered = 'true'
        })
        .catch((renderError) => {
          console.error('[Docs] page render failed', pageNumber, renderError)
        })
        .finally(() => {
          renderTasks.current.delete(pageNumber)
        })

      renderTasks.current.set(pageNumber, task)
    })
  }, [doc, visible])

  useImperativeHandle(
    ref,
    () => ({
      scrollToPage(page) {
        const container = scrollRef.current
        if (!container) return
        setVisible((current) => new Set(current).add(Number(page)))
        const target = container.querySelector(`[data-page="${page}"]`)
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      },
    }),
    [],
  )

  if (error) return <p className="docs-viewer-error">{error}</p>
  if (!doc) return <p className="docs-viewer-loading">Rendering document…</p>

  return (
    <div className="docs-pdf-scroll" ref={scrollRef}>
      {Array.from({ length: doc.numPages }, (_, index) => index + 1).map((pageNumber) => (
        <figure
          key={pageNumber}
          className={`docs-pdf-page${pageHint === pageNumber ? ' is-cited' : ''}`}
          data-page={pageNumber}
        >
          <canvas
            ref={(node) => {
              if (node) canvases.current.set(pageNumber, node)
              else canvases.current.delete(pageNumber)
            }}
          />
          <figcaption>p. {pageNumber}</figcaption>
        </figure>
      ))}
    </div>
  )
}

const PdfViewerWithRef = forwardRef(PdfViewer)

function TextViewer({ pages, pageHint }, ref) {
  const scrollRef = useRef(null)

  useImperativeHandle(
    ref,
    () => ({
      scrollToPage(page) {
        const container = scrollRef.current
        if (!container) return
        const target = container.querySelector(`[data-page="${page}"]`)
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      },
    }),
    [],
  )

  return (
    <div className="docs-pdf-scroll docs-text-scroll" ref={scrollRef}>
      {pages.map((page) => (
        <article
          key={page.page}
          className={`docs-text-page${pageHint === page.page ? ' is-cited' : ''}`}
          data-page={page.page}
        >
          <header>
            <span>{page.heading || 'page'}</span>
            <strong>p. {page.page}</strong>
          </header>
          {page.text.split(/\n{2,}/).map((paragraph, index) => (
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
    return <PdfViewerWithRef ref={viewerRef} fileUrl={doc.file_url} pageHint={pageHint} />
  }

  return <TextViewerWithRef ref={viewerRef} pages={doc.pages || []} pageHint={pageHint} />
}
