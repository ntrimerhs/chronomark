import { useState } from 'react'
import { supabase, AUTH_ENABLED } from '../lib/supabaseClient'

/* One click to an account, the way most people expect to sign in now.

   Supabase does the whole dance: it redirects to the provider, the provider
   redirects back to our /auth/callback, and the session lands in localStorage
   before the page even renders. Nothing is stored on our side, which is also
   why this works while the email confirmation still has no mailer.

   The buttons are guarded by AUTH_ENABLED for the same reason the rest of the
   form is: without a Supabase project there is nothing to talk to, and a
   button that does nothing is worse than no button. */

const PROVIDERS = [
  { id: 'google', label: 'Continue with Google' },
  { id: 'github', label: 'Continue with GitHub' },
]

export function oauthCallbackUrl(next) {
  const base = `${window.location.origin}/auth/callback`
  return next ? `${base}?next=${encodeURIComponent(next)}` : base
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 18 18" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.34A9 9 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.94H.96a9 9 0 0 0 0 8.12l3.01-2.34Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.46 3.44 1.35l2.58-2.58C13.46.89 11.42 0 9 0A9 9 0 0 0 .96 4.94l3.01 2.34C4.68 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  )
}

function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38l-.01-1.49c-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-2.9-.89-2.9-2.83 0-.63.22-1.15.6-1.55-.06-.15-.26-.74.06-1.53 0 0 .63-.2 2.06.77a5.6 5.6 0 0 1 1.5-.2c.51 0 1.02.07 1.5.2 1.43-.97 2.06-.77 2.06-.77.32.79.12 1.38.06 1.53.38.4.6.92.6 1.55 0 1.95-1.12 2.63-2.9 2.83.29.25.54.73.54 1.48l-.01 2.2c0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8Z"
      />
    </svg>
  )
}

const MARKS = { google: GoogleMark, github: GitHubMark }

export default function OAuthButtons({ next = '/workspaces', onError, disabled = false }) {
  const [pending, setPending] = useState(null)
  const [failure, setFailure] = useState('')

  if (!AUTH_ENABLED) return null

  const start = async (provider) => {
    if (pending) return
    setPending(provider)
    setFailure('')

    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider,
        options: { redirectTo: oauthCallbackUrl(next) },
      })
      if (error) throw error
      // The browser is already leaving for the provider; the button stays in
      // its pending state on purpose, because coming back is the next event.
    } catch (problem) {
      const message = problem?.message || 'Could not start that sign in.'
      setPending(null)
      setFailure(message)
      onError?.(message)
    }
  }

  return (
    <div className="auth-oauth">
      {PROVIDERS.map((provider) => {
        const Mark = MARKS[provider.id]
        return (
          <button
            key={provider.id}
            type="button"
            className="auth-oauth-btn"
            onClick={() => start(provider.id)}
            disabled={disabled || Boolean(pending)}
            data-provider={provider.id}
          >
            <span className="auth-oauth-mark">
              <Mark />
            </span>
            <span>{pending === provider.id ? 'Redirecting…' : provider.label}</span>
          </button>
        )
      })}

      {failure ? (
        <p className="auth-error" role="alert">
          {failure}
        </p>
      ) : null}

      <div className="auth-divider" aria-hidden="true">
        <span>or use an email</span>
      </div>
    </div>
  )
}
