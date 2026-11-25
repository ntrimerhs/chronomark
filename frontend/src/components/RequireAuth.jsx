import { Navigate, useLocation } from 'react-router-dom'
import useAuth from '../hooks/useAuth'
import '../styles/authDialog.css'

/* The door to the two workspaces.

   /upload and /documents are not marketing pages -- they cost a download, an
   OCR pass and an embedding bill per use, and every workspace row belongs to
   somebody. So the rule is simple: no session, no workspace. A signed-out
   visitor is sent to /register with the page they wanted kept in ?next, and
   lands back there the moment they finish signing up.

   While the session is still being read we render a quiet placeholder instead
   of the workspace, otherwise the shell flashes for a frame before the
   redirect and it looks like a bug. */

export default function RequireAuth({ children }) {
  const { session, ready, enabled } = useAuth()
  const location = useLocation()

  if (!enabled) return children

  if (!ready) {
    return (
      <main className="auth-guard">
        <div className="auth-guard-card">
          <span className="auth-guard-dot" aria-hidden="true" />
          <p>Checking your session…</p>
        </div>
      </main>
    )
  }

  if (!session) {
    const wanted = `${location.pathname}${location.search}`
    return <Navigate to={`/register?next=${encodeURIComponent(wanted)}`} replace />
  }

  return children
}
