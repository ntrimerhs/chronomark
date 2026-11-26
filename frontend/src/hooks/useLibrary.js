/* The library: the conversations this account has, plus the files behind them.

   The sidebar needs one list, and it needed it a second ago. Three changes make
   that true: each request updates its own piece of state the moment it lands
   (nothing waits for the slowest), the conversation list is painted from the
   last copy kept in localStorage before the network is asked, and the history
   request is the one that decides the loading state -- the documents and videos
   are not on the critical path any more. */

import { useCallback, useEffect, useState } from 'react'
import axios from 'axios'
import { API_BASE_URL } from '../config'
import { supabase, AUTH_ENABLED } from '../lib/supabaseClient'

// One cache per account: the list is someone's own conversations, and two
// people share a browser.
async function cacheKey() {
  if (!AUTH_ENABLED) return 'cm.conversations.anon'
  try {
    const { data } = await supabase.auth.getSession()
    const id = data?.session?.user?.id
    return id ? `cm.conversations.${id}` : 'cm.conversations.anon'
  } catch {
    return 'cm.conversations.anon'
  }
}

function readCache() {
  try {
    const raw = window.localStorage.getItem('cm.conversations.anon')
    const parsed = raw ? JSON.parse(raw) : null
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeCache(conversations) {
  try {
    window.localStorage.setItem('cm.conversations.anon', JSON.stringify(conversations))
  } catch {
    /* a full quota is not a reason to break the page */
  }
}

export default function useLibrary() {
  const [documents, setDocuments] = useState([])
  const [videos, setVideos] = useState([])
  const [conversations, setConversations] = useState(readCache)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    // Paint from the account's own copy before the network is asked.
    const key = await cacheKey()
    try {
      const raw = window.localStorage.getItem(key)
      const parsed = raw ? JSON.parse(raw) : null
      if (Array.isArray(parsed) && parsed.length) setConversations(parsed)
    } catch {
      /* a broken cache is not a broken page */
    }

    const conversationsRequest = axios
      .get(`${API_BASE_URL}/api/conversations`, { timeout: 30000 })
      .then(({ data }) => {
        const items = data?.conversations || []
        setConversations(items)
        try {
          window.localStorage.setItem(key, JSON.stringify(items))
        } catch {
          /* a full quota is not a reason to break the page */
        }
      })
      .catch((requestError) => {
        setError(requestError?.response?.data?.detail || 'Could not load your history.')
      })
      .finally(() => setLoading(false))

    const documentsRequest = axios
      .get(`${API_BASE_URL}/api/documents`, { timeout: 30000 })
      .then(({ data }) => setDocuments(data?.documents || []))
      .catch(() => {
        /* the history still lists; the file count is the only casualty */
      })

    const videosRequest = axios
      .get(`${API_BASE_URL}/api/videos`, { timeout: 30000 })
      .then(({ data }) => setVideos(data?.videos || []))
      .catch(() => {
        /* same: a workspace with no videos is not an error worth showing */
      })

    await Promise.allSettled([conversationsRequest, documentsRequest, videosRequest])
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { documents, videos, conversations, loading, error, refresh }
}
