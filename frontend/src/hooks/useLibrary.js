/* The library: every document and every recording this account has analysed.

   The sidebar used to show something different in each workspace -- the open
   document's conversations in one, nothing at all in another -- so a reader who
   had just uploaded a file saw an empty column and concluded their history was
   gone. One list, fetched the same way everywhere, is the fix. */

import { useCallback, useEffect, useState } from 'react'
import axios from 'axios'
import { API_BASE_URL } from '../config'

export default function useLibrary() {
  const [documents, setDocuments] = useState([])
  const [videos, setVideos] = useState([])
  const [conversations, setConversations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    const [docs, vids, chats] = await Promise.allSettled([
      axios.get(`${API_BASE_URL}/api/documents`, { timeout: 30000 }),
      axios.get(`${API_BASE_URL}/api/videos`, { timeout: 30000 }),
      axios.get(`${API_BASE_URL}/api/conversations`, { timeout: 30000 }),
    ])
    if (docs.status === 'fulfilled') {
      setDocuments(docs.value.data?.documents || [])
    } else {
      setError(
        docs.reason?.response?.data?.detail || 'Could not load your documents.',
      )
    }
    // A workspace with no videos is not an error worth showing: the endpoint
    // is newer than the deployment of it, and the documents still list.
    if (vids.status === 'fulfilled') {
      setVideos(vids.value.data?.videos || [])
    }
    if (chats.status === 'fulfilled') {
      setConversations(chats.value.data?.conversations || [])
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { documents, videos, conversations, loading, error, refresh }
}
