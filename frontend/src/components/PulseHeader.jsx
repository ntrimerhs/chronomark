import { useEffect, useState } from 'react'
import CommandPalette from './CommandPalette'
import './../styles/pulseHeader.css'

/* The bar from the landing page, shared.

   The mark on the left with its search underneath the same hairline, the section
   pills in the middle, Sign in and Get Started on the right.

   Two modes: `fixed` floats over the plate (the landing page), `inline` takes a
   76px band in normal flow, which is exactly the height the upload and documents
   screens already reserve, so their viewport maths still add up. */

// [label, section id]. Which one reads as current is worked out from the page,
// not from the order of this list: the first entry used to be hardcoded as
// current, so every pill you clicked left Platform looking selected.
const NAV = [
  ['Platform', 'platform'],
  ['Technology', 'technology'],
  ['Pricing', 'pricing'],
]

export default function PulseHeader({ inline = false, reloadOnBrand = false }) {
  const [active, setActive] = useState('platform')

  // The pill that is current is the section the reader is actually in. Measured
  // on scroll rather than set by the click, so a pill never stays selected after
  // you have scrolled past it.
  useEffect(() => {
    let frame = 0

    const measure = () => {
      frame = 0
      const marker = window.innerHeight * 0.4
      let current = NAV[0][1]
      for (const [, id] of NAV) {
        const section = document.getElementById(id)
        if (!section) continue
        const { top } = section.getBoundingClientRect()
        if (top - marker <= 0) current = id
      }
      setActive(current)
    }

    const onScroll = () => {
      if (frame) return
      frame = window.requestAnimationFrame(measure)
    }

    measure()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      if (frame) window.cancelAnimationFrame(frame)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  return (
    <header className={`ph${inline ? ' is-inline' : ''}`}>
      <div className="ph-inner">
        <div className="ph-brand-wrap">
          <a
            className="ph-brand"
            href="/"
            aria-label="Chronomark"
            onClick={
              reloadOnBrand
                ? (event) => {
                    event.preventDefault()
                    window.location.reload()
                  }
                : undefined
            }
          >
            <span className="ph-brand-label">CHRONOMARK</span>
            <span className="ph-brand-dot" aria-hidden="true" />
          </a>
          <span className="ph-brand-divider" aria-hidden="true" />
          <div className="ph-search-slot">
            <CommandPalette />
          </div>
        </div>

        <nav className="ph-nav" aria-label="Sections">
          {NAV.map(([label, id]) => (
            <a
              key={id}
              href={`#${id}`}
              className={id === active ? 'is-current' : undefined}
              aria-current={id === active ? 'true' : undefined}
              onClick={(event) => {
                const section = document.getElementById(id)
                if (!section) return
                // Scrolled here rather than left to the browser: the app's scroll
                // container is not always the document, and CSS scroll-behavior
                // only covers the element that actually scrolls.
                event.preventDefault()
                setActive(id)
                section.scrollIntoView({ behavior: 'smooth', block: 'start' })
                window.history.replaceState(null, '', `#${id}`)
              }}
            >
              {label}
            </a>
          ))}
        </nav>

        <div className="ph-actions">
          <a className="ph-signin" href="#platform">
            Sign in
          </a>
          <a className="ph-start" href="/upload">
            <span>Get Started</span>
            <span className="material-symbols-outlined">arrow_forward</span>
          </a>
        </div>
      </div>
    </header>
  )
}
