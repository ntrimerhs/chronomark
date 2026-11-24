import { useEffect } from 'react'
import AuthForm from './AuthForm'
import '../styles/authDialog.css'

/* The dialog the header opens.

   Sign in and create account in one place: the same two fields either way, and
   someone who typed their password on the wrong tab only has to click the
   other tab. The form itself lives in AuthForm so the register page is
   literally the same component with more room. */

const COPY = {
  signin: {
    title: 'Welcome back',
    sub: 'Sign in to your workspaces.',
  },
  signup: {
    title: 'Create your account',
    sub: 'Your documents and recordings stay yours.',
  },
}

export default function AuthDialog({ open, mode = 'signin', onClose, onModeChange }) {
  const copy = COPY[mode] || COPY.signin

  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="auth-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="auth-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button type="button" className="auth-close" onClick={onClose} aria-label="Close">
          ×
        </button>

        <div className="auth-head">
          <span className="auth-mark" aria-hidden="true">
            <span className="auth-mark-dot" />
          </span>
          <h2 id="auth-title">{copy.title}</h2>
          <p>{copy.sub}</p>
        </div>

        <AuthForm mode={mode} onModeChange={onModeChange} onSuccess={onClose} />
      </div>
    </div>
  )
}
