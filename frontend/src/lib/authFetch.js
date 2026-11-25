/* Every backend call carries the signed-in user's access token.

   The endpoints that cost money are guarded on the server, so the browser has
   to prove who it is on each request. Rather than edit thirty fetch calls and
   forget the thirty-first, the token is attached once here, to any request
   that leaves for API_BASE_URL -- including the ones written next month.

   Nothing else changes: only the Authorization header is added, only for our
   own backend, and only when there is a session to prove. */

import { API_BASE_URL } from '../config'
import { supabase, AUTH_ENABLED } from './supabaseClient'

const nativeFetch = window.fetch.bind(window)
const BASE = String(API_BASE_URL || '').replace(/\/+$/, '')

async function accessToken() {
  if (!AUTH_ENABLED) return null
  try {
    const { data } = await supabase.auth.getSession()
    return data?.session?.access_token ?? null
  } catch {
    return null
  }
}

function urlOf(input) {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  return input?.url ?? ''
}

function isOurApi(url) {
  if (!url || !BASE) return false
  if (url.startsWith('/')) {
    // A relative call is same-origin, which in development is the Vite proxy
    // and in production is Caddy in front of this same backend.
    return true
  }
  return url.startsWith(BASE)
}

export function installAuthFetch() {
  if (window.__cmAuthFetch) return
  window.__cmAuthFetch = true

  window.fetch = async (input, init) => {
    const url = urlOf(input)
    if (!isOurApi(url) || url.includes('/auth/v1/')) {
      return nativeFetch(input, init)
    }

    // A Request object carries its own headers; a plain call carries an init.
    const request = typeof input === 'object' && input !== null && 'headers' in input && !init
      ? input
      : null
    const existing = init?.headers ?? request?.headers
    const headers = new Headers(existing || undefined)
    if (headers.has('Authorization')) {
      return nativeFetch(input, init)
    }

    const token = await accessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)

    if (request) {
      return nativeFetch(new Request(request, { headers }))
    }
    return nativeFetch(input, { ...(init || {}), headers })
  }
}

installAuthFetch()
