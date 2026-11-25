import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import useAuth from '../hooks/useAuth'
import '../styles/authDialog.css'

/* Where Google and GitHub come back to.

   By the time this page renders, supabase-js has already read the tokens out
   of the URL and stored the session, so there is nothing to exchange here --
   this page only has to wait for that session to appear in the hook and then
   forward to the workspace the visitor originally asked for.

   It also has to be the page that explains a refusal. If the provider says no
   (a cancelled consent, a client id that does not match), the reason arrives
   in the URL and would otherwise be swallowed by the redirect. */

function errorFromUrl() {
  const hash = window.location.hash.startsWith('#')
    ? window.location.hash.slice(1)
    : window.location.hash
  const fromHash = new URLSearchParams(hash)
  const fromQuery = new URLSearchParams(window.location.search)
  const description =
    fromHash.get('error_description') ||
    fromQuery.get('error_description') ||
    fromHash.get('error') ||
    fromQuery.get('error')
  return description ? description.replace(/\+/g, ' ') : ''
}

/* ?next comes from the address bar, so it is not trusted: only a path on this
   site is a destination. Anything else would turn our own login page into a
   stepping stone to a stranger's site. */
function safeNext(value, fallback = '/upload') {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return fallback
  return value
}

export default function AuthCallback() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { session, ready, enabled } = useAuth()
  const [failure] = useState(errorFromUrl)
  const [waited, setWaited] = useState(false)

  const next = safeNext(params.get('next'))

  useEffect(() => {
    const timer = window.setTimeout(() => setWaited(true), 9000)
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (!enabled) return
    if (ready && session) navigate(next, { replace: true })
  }, [enabled, ready, session, navigate, next])

  const stuck = !failure && enabled && ready && !session && waited

  return (
    <main className="auth-page auth-callback">
      <div className="auth-page-plate" aria-hidden="true" />

      <a className="auth-page-brand" href="/">
        <span>CHRONOMARK</span>
        <i />
      </a>

      <section className="auth-page-card auth-callback-card">
        {failure || stuck ? (
          <>
            <div className="auth-head">
              <span className="auth-mark" aria-hidden="true">
                <span className="auth-mark-dot" />
              </span>
              <h2>That sign in did not finish</h2>
              <p>
                {failure
                  ? failure
                  : 'The provider sent you back without a session. Try again, or use your email.'}
              </p>
            </div>
            <a className="auth-submit auth-callback-link" href={`/login?next=${encodeURIComponent(next)}`}>
              Try again
            </a>
            <p className="auth-swap">
              <a href={`/register?next=${encodeURIComponent(next)}`}>Create an account with an email</a>
            </p>
          </>
        ) : (
          <div className="auth-callback-wait">
            <span className="auth-guard-dot" aria-hidden="true" />
            <p>Finishing sign in…</p>
          </div>
        )}
      </section>
    </main>
  )
}
