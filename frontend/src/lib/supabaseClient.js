import { createClient } from '@supabase/supabase-js'

// The two values are baked in at build time (docker compose build args). The
// publishable key is meant to be public: every row is guarded by row level
// security in the database, not by the key.
const url = import.meta.env.VITE_SUPABASE_URL
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

export const supabase =
  url && publishableKey
    ? createClient(url, publishableKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
        },
      })
    : null

export const AUTH_ENABLED = Boolean(supabase)

// Accounts are created with an email, but nobody wants to type one to log in.
// A bare word is read as a username on this domain, so "admin" and
// "admin@chronomark.app" are the same login.
export const USERNAME_DOMAIN = '@chronomark.app'

export function toEmail(value) {
  const cleaned = (value || '').trim()
  if (!cleaned) return ''
  return cleaned.includes('@') ? cleaned : `${cleaned}${USERNAME_DOMAIN}`
}

export function displayNameOf(session) {
  if (!session?.user) return ''
  const metadata = session.user.user_metadata || {}
  return metadata.full_name || metadata.name || (session.user.email || '').split('@')[0]
}
