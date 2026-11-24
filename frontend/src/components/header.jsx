import { useState } from 'react'
import { Menu, X } from 'lucide-react'
import CommandPalette from './CommandPalette'
import '../styles/header.css'

/* The navigation, to the Electric Pulse reference: a lime star mark beside the
   wordmark, three section links, the acid-lime call to action, and a hamburger
   that opens the same links as a panel on small screens.

   The command palette stays mounted: it is the site's search, not decoration. */

const NAV_LINKS = [
  { href: '/#features', label: 'Features' },
  { href: '/upload', label: 'Solutions' },
  { href: '/documents', label: 'Resources' },
]

export default function Header() {
  const [open, setOpen] = useState(false)

  return (
    <header className="pulse-header">
      <div className="pulse-shell pulse-nav">
        <a className="pulse-brand" href="/" aria-label="Chronomark home">
          <svg className="pulse-star" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M16 0c1.6 9 4.2 13 16 16-11.8 3-14.4 7-16 16C14.4 23 11.8 19 0 16 11.8 13 14.4 9 16 0Z" />
          </svg>
          <span>
            Chronomark <b>AI</b>
          </span>
        </a>

        <nav className="pulse-links" aria-label="Primary">
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href}>
              {link.label}
            </a>
          ))}
        </nav>

        <div className="pulse-nav-actions">
          <span className="pulse-search">
            <CommandPalette />
          </span>

          <a href="/upload" className="pulse-cta">
            Try Now
            <span aria-hidden="true">↗</span>
          </a>

          <button
            type="button"
            className="pulse-burger"
            onClick={() => setOpen((value) => !value)}
            aria-label={open ? 'Close menu' : 'Open menu'}
            aria-expanded={open}
            aria-controls="pulse-mobile-menu"
          >
            {open ? <X size={19} /> : <Menu size={19} />}
          </button>
        </div>
      </div>

      <nav
        id="pulse-mobile-menu"
        className={`pulse-mobile${open ? ' is-open' : ''}`}
        aria-label="Mobile navigation"
      >
        {NAV_LINKS.map((link) => (
          <a key={link.href} href={link.href} onClick={() => setOpen(false)}>
            {link.label}
          </a>
        ))}
        <a href="/upload" onClick={() => setOpen(false)}>
          Try Now ↗
        </a>
      </nav>
    </header>
  )
}
