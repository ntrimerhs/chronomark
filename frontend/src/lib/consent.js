import axios from 'axios'
import { API_BASE_URL } from '../config'
import { supabase, AUTH_ENABLED } from './supabaseClient'

async function headers() {
  if (!AUTH_ENABLED) return {}
  try {
    const { data } = await supabase.auth.getSession()
    const token = data?.session?.access_token
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

export async function fetchConsents() {
  const { data } = await axios.get(`${API_BASE_URL}/api/consent`, { headers: await headers() })
  return data
}

export async function saveConsent(kind, granted) {
  const { data } = await axios.post(
    `${API_BASE_URL}/api/consent`,
    { [kind]: !!granted },
    { headers: await headers() },
  )
  return data
}

export async function exportAccount() {
  const { data } = await axios.get(`${API_BASE_URL}/api/account/export`, { headers: await headers() })
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'chronomark-export.json'
  a.click()
  URL.revokeObjectURL(url)
}

export async function deleteAccount() {
  await axios.delete(`${API_BASE_URL}/api/account`, {
    headers: await headers(),
    data: { confirm: 'DELETE' },
  })
}
