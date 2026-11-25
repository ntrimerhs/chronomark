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
  ['Platform', 'platform', true],
  ['Technology', 'technology', false],
  ['Pricing', 'pricing', false],
]

export default function PulseHeader({ inline = false, reloadOnBrand = false }) {
  const { session, enabled, signOut } = useAuth()
  const [dialog, setDialog] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)
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

            <a className="ph-start" href={session ? '/upload' : '/register'}>
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
