import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import useAuth from '../hooks/useAuth'
import { supabase } from '../lib/supabaseClient'
import '../styles/authDialog.css'

/* /reset-password.

   The link Supabase mails back lands here with a recovery session already in the
   URL (detectSessionInUrl handles the token), so this page only has to collect
   the new password. If there is no recovery session the link was already used or
   expired, and the page says so instead of showing a form that cannot work. */

export default function ResetPasswordPage() {
  const navigate = useNavigate()
  const { session, ready } = useAuth()

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!done) return undefined
    const timer = setTimeout(() => navigate('/upload', { replace: true }), 1600)
    return () => clearTimeout(timer)
  }, [done, navigate])

  const submit = async (event) => {
    event.preventDefault()
    if (busy) return

    if (password.length < 8) {
      setError('The password needs at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('The two passwords do not match.')
      return
    }

    setBusy(true)
    setError('')

    try {
      if (!supabase) throw new Error('Sign in is not configured on this build.')
      const { error: updateError } = await supabase.auth.updateUser({ password })
      if (updateError) throw new Error(updateError.message)
      setDone(true)
    } catch (problem) {
      setError(problem.message || 'Could not set the new password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-page-plate" aria-hidden="true" />

      <a className="auth-page-brand" href="/">
        <span>CHRONOMARK</span>
        <i />
      </a>

      <section className="auth-page-card">
        <div className="auth-head">
          <img className="auth-mark" src="/cm-c-192.png" alt="" width="46" height="46" />
          <h2>Set a new password</h2>
          <p>One password, then you are back in your workspaces.</p>
        </div>

        {done ? (
          <div className="auth-form is-page">
            <p className="auth-note" role="status">
              Password updated. Taking you to the workspace…
            </p>
          </div>
        ) : !ready ? (
          <div className="auth-form is-page">
            <p className="auth-hint">Checking the link…</p>
          </div>
        ) : !session ? (
          <div className="auth-form is-page">
            <p className="auth-error" role="alert">
              This reset link has expired or was already used.
            </p>
            <p className="auth-hint">
              Ask for a new one and open it soon after it arrives.
            </p>
            <a className="auth-submit" href="/login">
              Request a new link
            </a>
          </div>
        ) : (
          <form className="auth-form is-page" onSubmit={submit}>
            <label className="auth-field">
              <span>New password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="At least 8 characters"
                autoComplete="new-password"
                autoFocus
              />
            </label>

            <label className="auth-field">
              <span>Repeat it</span>
              <input
                type="password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                placeholder="The same password again"
                autoComplete="new-password"
              />
            </label>

            {error ? (
              <p className="auth-error" role="alert">
                {error}
              </p>
            ) : null}

            <button type="submit" className="auth-submit" disabled={busy}>
              <span>{busy ? 'Working…' : 'Set password'}</span>
              <svg
                className="auth-submit-arrow"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </button>
          </form>
        )}
      </section>

      <p className="auth-page-foot">
        <a href="/login">Back to sign in</a>
      </p>
    </main>
  )
}
