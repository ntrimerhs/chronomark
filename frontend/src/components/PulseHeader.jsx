import { useEffect } from 'react'
import CommandPalette from './CommandPalette'
import './../styles/pulseHeader.css'

/* The bar from the landing page, shared.

   The mark on the left with its search underneath the same hairline, the section
   pills in the middle, Sign in and Get Started on the right.

   Two modes: `fixed` floats over the plate (the landing page), `inline` takes a
   76px band in normal flow, which is exactly the height the upload and documents
   screens already reserve, so their viewport maths still add up. */

const NAV = [
  ['Platform', 'platform', true],
  ['Technology', 'technology', false],
  ['Research', 'research', false],
  ['Pricing', 'pricing', false],
]

export default function PulseHeader({ inline = false, reloadOnBrand = false }) {
  useEffect(() => {}, [])

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
          {NAV.map(([label, path, current]) => (
            <a key={path} href={`#${path}`} className={current ? 'is-current' : undefined}>
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
