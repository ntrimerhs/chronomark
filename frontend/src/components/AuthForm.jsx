import { useState } from 'react'
import { API_BASE_URL } from '../config'
import { supabase, toEmail, USERNAME_DOMAIN } from '../lib/supabaseClient'

/* The two fields, either way they are shown.

   The dialog and the register page are the same form: same validation, same
   endpoint, same error text. Keeping them one component means a fix here is a
   fix in both, which is the whole reason the login has two entry points.

   Sign in goes straight to Supabase from the browser (the publishable key is
   public by design). Sign up goes through our own endpoint instead, because
   Supabase would otherwise mail a confirmation link and this project has no
   mailer -- that endpoint creates the account already confirmed, so
   registration ends in a session rather than in an inbox. */

export default function AuthForm({ mode = 'signin', onModeChange, onSuccess, compact = true }) {
  const [name, setName] = useState('')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const signup = mode === 'signup'

  const submit = async (event) => {
    event.preventDefault()
    if (busy) return

    const email = toEmail(account)
    if (!email) {
      setError('Enter an email or a username.')
      return
    }
    if (password.length < 8) {
      setError('The password needs at least 8 characters.')
      return
    }

    setBusy(true)
    setError('')

    try {
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

  return (
    <form className={`auth-form${compact ? '' : ' is-page'}`} onSubmit={submit}>
      {signup && (
        <label className="auth-field">
          <span>Name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Marios"
            autoComplete="name"
            autoFocus
          />
        </label>
      )}

      <label className="auth-field">
        <span>Email or username</span>
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
      <p className="auth-hint">
        A bare username signs in as <code>&lt;name&gt;{USERNAME_DOMAIN}</code>.
      </p>

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

      {error ? (
        <p className="auth-error" role="alert">
          {error}
        </p>
      ) : null}

      <button type="submit" className="auth-submit" disabled={busy}>
        {busy ? 'Working…' : signup ? 'Create account' : 'Sign in'}
      </button>

      {onModeChange ? (
        <p className="auth-swap">
          {signup ? 'Already have an account?' : 'No account yet?'}{' '}
          <button type="button" onClick={() => onModeChange(signup ? 'signin' : 'signup')}>
            {signup ? 'Sign in' : 'Create one'}
          </button>
        </p>
      ) : null}
    </form>
  )
}
