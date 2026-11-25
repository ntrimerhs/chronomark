/* axios needs the session token too -- not every call goes through fetch.

   authFetch.js wraps window.fetch, which covers the SSE stream and anything new
   written against fetch. But the upload pages, the workspace and both chat
   surfaces are written with axios, and axios uses XMLHttpRequest in the
   browser: it never touches window.fetch, so those requests left without a
   token and the guarded endpoints answered 401 "Sign in to use this feature."
   -- which the page showed as a failed upload, while the visitor was signed in.

   One interceptor here fixes every axios call, including the ones written next
   month, so nobody has to remember to pass headers by hand again. */

import axios from 'axios'
import { API_BASE_URL } from '../config'
import { supabase, AUTH_ENABLED } from './supabaseClient'

const BASE = String(API_BASE_URL || '').replace(/\/+$/, '')
let installed = false

async function accessToken() {
  if (!AUTH_ENABLED) return null
  try {
    const { data } = await supabase.auth.getSession()
    return data?.session?.access_token ?? null
  } catch {
    return null
  }
}

function isOurApi(url) {
  if (!url || !BASE) return false
  // A relative call is same-origin: the Vite proxy in development, Caddy in
  // production. Anything else is a third party and keeps its own headers.
  return url.startsWith('/') || url.startsWith(BASE)
}

export function installAuthAxios() {
  if (installed) return
  installed = true
  // Same marker idea as authFetch: a build can be checked for having shipped
  // this file without a browser.
  window.__cmAuthAxios = true

  axios.interceptors.request.use(async (config) => {
    try {
      const url = String(config.url || '')
      if (!isOurApi(url) || url.includes('/auth/v1/')) return config

      const headers = config.headers || (config.headers = {})
      const existing = headers.Authorization || headers.authorization
      if (existing) return config

      const token = await accessToken()
      if (token) headers.Authorization = `Bearer ${token}`
    } catch {
      // Never break a request over a missing token: the gate will answer 401
      // with a reason, which is clearer than a client-side throw.
    }
    return config
  })
}

installAuthAxios()
