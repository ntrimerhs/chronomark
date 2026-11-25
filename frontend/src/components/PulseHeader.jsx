import { useEffect, useRef, useState } from 'react'
import CommandPalette from './CommandPalette'
import AuthDialog from './AuthDialog'
import useAuth from '../hooks/useAuth'
import { displayNameOf } from '../lib/supabaseClient'
import './../styles/pulseHeader.css'
import './../styles/authDialog.css'

/* The bar from the landing page, shared.

   The mark on the left with its search underneath the same hairline, the section
   pills in the middle, Sign in and the filled Sign up action on the right.

   Two modes: `fixed` floats over the plate (the landing page), `inline` takes a
   76px band in normal flow, which is exactly the height the upload and documents
   screens already reserve, so their viewport maths still add up.

   The filled action is the sign-up: it is the only thing a visitor who has just
   read the page needs. Once there is a session the same slot opens the
   workspaces instead, because signing up twice is not a thing.

   The account controls are the real ones: the dialog signs in against Supabase
   and the chip is that session, so the header and the workspaces cannot disagree
   about who is using the product. */

const NAV = [
  ['Platform', 'platform'],
  ['Technology', 'technology'],
  ['Pricing', 'pricing'],
]

/* Where the reading position counts as "at" a section: just under the floating
   bar, so a pill lights up when its heading reaches the top of the sheet rather
   than when the section merely appears at the bottom edge. */
const READING_LINE = 160

export default function PulseHeader({ inline = false, reloadOnBrand = false }) {
  const { session, enabled, signOut } = useAuth()
  const [dialog, setDialog] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [current, setCurrent] = useState('platform')
  const accountRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return undefined
    const onDown = (event) => {
      if (accountRef.current && !accountRef.current.contains(event.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menuOpen])

  /* The pills follow the page, not the click: the section whose heading last
     passed the reading line is the one lit. #root is the app's scroll container,
     so the listener goes there as well as on the window. */
  useEffect(() => {
    const root = document.getElementById('root')

    const read = () => {
      let found = NAV[0][1]
      NAV.forEach(([, id]) => {
        const element = document.getElementById(id)
        if (element && element.getBoundingClientRect().top <= READING_LINE) found = id
      })
      setCurrent(found)
    }

    read()
    window.addEventListener('scroll', read, { passive: true })
    window.addEventListener('resize', read)
    root?.addEventListener('scroll', read, { passive: true })

    return () => {
      window.removeEventListener('scroll', read)
      window.removeEventListener('resize', read)
      root?.removeEventListener('scroll', read)
    }
  }, [inline])

  const goTo = (event, id) => {
    const target = document.getElementById(id)
    // A section only exists on the landing page; from a workspace the pill has
    // to travel there first.
    if (!target) return

    event.preventDefault()
    setCurrent(id)
    window.history.replaceState(null, '', `#${id}`)

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  }

  const name = displayNameOf(session)
  const initials = (name || session?.user?.email || '?').slice(0, 2)

  return (
    <>
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
              {/* The mark instead of the letters and the dot: the same logo
                  the sidebar carries, so the two never disagree. */}
              <img className="ph-brand-mark" src="/cm-mark-192.png" alt="Chronomark" />
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
                className={current === id ? 'is-current' : undefined}
                aria-current={current === id ? 'true' : undefined}
                onClick={(event) => goTo(event, id)}
              >
                {label}
              </a>
            ))}
          </nav>

          <div className="ph-actions">
            {enabled && !session && (
              <button type="button" className="ph-signin" onClick={() => setDialog('signin')}>
                Sign in
              </button>
            )}

            {session && (
              <div className="ph-account" ref={accountRef}>
                <button
                  type="button"
                  className="ph-account-button"
                  onClick={() => setMenuOpen((open) => !open)}
                  aria-expanded={menuOpen}
                  aria-haspopup="menu"
                >
                  <span className="ph-account-initials">{initials}</span>
                  <span className="ph-account-name">{name}</span>
                </button>

                {menuOpen && (
                  <div className="ph-account-menu" role="menu">
                    <div className="ph-account-email">{session.user.email}</div>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false)
                        signOut()
                      }}
                    >
                      Sign out
                    </button>
                  </div>
                )}
              </div>
            )}

            <a className="ph-start" href={session ? '/workspaces' : '/register'}>
              <span>{session ? 'Workspaces' : 'Get Started'}</span>
              <span className="material-symbols-outlined">arrow_forward</span>
            </a>
          </div>
        </div>
      </header>

      <AuthDialog
        open={dialog !== null}
        mode={dialog || 'signin'}
        onClose={() => setDialog(null)}
        onModeChange={setDialog}
      />
    </>
  )
}
