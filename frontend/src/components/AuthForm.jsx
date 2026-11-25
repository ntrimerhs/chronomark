import { useState } from 'react'
import { API_BASE_URL } from '../config'
import { supabase, toEmail, USERNAME_DOMAIN } from '../lib/supabaseClient'
import OAuthButtons from './OAuthButtons'

/* The two fields, in the three shapes they are shown.

   The dialog and the register page are the same form: same validation, same
   endpoint, same error text. Keeping them one component means a fix here is a
   fix in both, which is the whole reason the login has more than one entry point.

   Sign in goes straight to Supabase from the browser (the publishable key is
   public by design). Sign up goes through our own endpoint instead, because
   Supabase would otherwise mail a confirmation link and this project has no
   mailer -- that endpoint creates the account already confirmed, so registration
   ends in a session rather than in an inbox.

   Reset asks for the address only and lets Supabase mail the link; the link
   returns to /reset-password, which is where the new password is typed. */

export default function AuthForm({
  mode = 'signin',
  onModeChange,
  onSuccess,
  compact = true,
  oauthNext = '/workspaces',
}) {
  const [name, setName] = useState('')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sentTo, setSentTo] = useState('')

  const signup = mode === 'signup'
  const reset = mode === 'reset'

  const submit = async (event) => {
    event.preventDefault()
    if (busy) return

    const email = toEmail(account)
    if (!email) {
      setError('Enter an email or a username.')
      return
    }

    setBusy(true)
    setError('')

    try {
      if (reset) {
        if (!supabase) throw new Error('Sign in is not configured on this build.')
        const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
          redirectTo: `${window.location.origin}/reset-password`,
        })
        if (resetError) throw new Error(resetError.message)
        setSentTo(email)
        return
      }

      if (password.length < 8) {
        setError('The password needs at least 8 characters.')
        return
      }

      if (signup) {
        const response = await fetch(`${API_BASE_URL}/auth/signup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email,
            password,
            full_name: name.trim() || undefined,
          }),
        })

        if (!response.ok) {
          const detail = await response.json().catch(() => ({}))
          throw new Error(detail.detail || 'Could not create the account.')
        }
      }

      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      })
      if (signInError) throw new Error(signInError.message)

      onSuccess?.()
    } catch (problem) {
      setError(problem.message || 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  if (reset && sentTo) {
    return (
      <div className={`auth-form${compact ? '' : ' is-page'}`}>
        <p className="auth-note" role="status">
          If that address has an account, a reset link is on its way to <strong>{sentTo}</strong>.
          It opens a page where you set a new password.
        </p>
        <p className="auth-hint">
          Nothing after a minute or two? Check the spam folder, then ask for it again.
        </p>
        {onModeChange ? (
          <p className="auth-swap">
            <button type="button" onClick={() => onModeChange('signin')}>
              Back to sign in
            </button>
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <form className={`auth-form${compact ? '' : ' is-page'}`} onSubmit={submit}>
      <OAuthButtons next={oauthNext} onError={setError} disabled={busy} />

      {signup && (
        <label className="auth-field">
          <span>Name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Your First Name"
            autoComplete="name"
            autoFocus
          />
        </label>
      )}

      <label className="auth-field">
        <span>{reset ? 'Email' : 'Email or username'}</span>
        <input
          type="text"
          value={account}
          onChange={(event) => setAccount(event.target.value)}
          placeholder="you@example.com"
          autoComplete="username"
          spellCheck="false"
          autoCapitalize="none"
          autoFocus={!signup}
        />
      </label>

      {!reset && (
        <p className="auth-hint">
          A bare username signs in as <code>&lt;name&gt;{USERNAME_DOMAIN}</code>.
        </p>
      )}

      {!reset && (
        <>
          <label className="auth-field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="At least 8 characters"
              autoComplete={signup ? 'new-password' : 'current-password'}
            />
          </label>

          {!signup && onModeChange ? (
            <p className="auth-forgot">
              <button type="button" onClick={() => onModeChange('reset')}>
                Forgot password?
              </button>
            </p>
          ) : null}
        </>
      )}

      {error ? (
        <p className="auth-error" role="alert">
          {error}
        </p>
      ) : null}

      {signup && (
        <p style={{ fontSize: 12, lineHeight: 1.5, color: '#a7acba', margin: '4px 0 0' }}>
          By creating an account you agree to our <a href="/privacy" target="_blank" rel="noreferrer">Privacy Policy</a>.
          To answer your questions, the text of your files and your questions are sent to AI providers,
          including DeepSeek, whose servers are in China. We ask for your explicit consent before your
          first upload. Uploaded files are deleted after 3 hours.
        </p>
      )}

      <button type="submit" className="auth-submit" disabled={busy}>
        <span>{busy ? 'Working…' : reset ? 'Send reset link' : signup ? 'Create account' : 'Sign in'}</span>
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

      {onModeChange ? (
        <p className="auth-swap">
          {reset ? (
            <button type="button" onClick={() => onModeChange('signin')}>
              Back to sign in
            </button>
          ) : (
            <>
              {signup ? 'Already have an account?' : 'No account yet?'}{' '}
              <button type="button" onClick={() => onModeChange(signup ? 'signin' : 'signup')}>
                {signup ? 'Sign in' : 'Create one'}
              </button>
            </>
          )}
        </p>
      ) : null}
    </form>
  )
}
