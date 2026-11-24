import { useEffect, useState } from 'react'
import { supabase, AUTH_ENABLED } from '../lib/supabaseClient'

/* The signed-in account, as the header needs it.

   One subscription, no polling: Supabase keeps the session in localStorage and
   tells us when it changes (sign in, sign out, token refresh, another tab). */
export default function useAuth() {
  const [session, setSession] = useState(null)
  const [ready, setReady] = useState(!AUTH_ENABLED)

  useEffect(() => {
    if (!AUTH_ENABLED) return undefined

    let alive = true
    supabase.auth.getSession().then(({ data }) => {
      if (!alive) return
      setSession(data.session ?? null)
      setReady(true)
    })

    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      if (!alive) return
      setSession(next ?? null)
      setReady(true)
    })

    return () => {
      alive = false
      data?.subscription?.unsubscribe?.()
    }
  }, [])

  return {
    session,
    ready,
    enabled: AUTH_ENABLED,
    signOut: () => supabase?.auth.signOut(),
  }
}
