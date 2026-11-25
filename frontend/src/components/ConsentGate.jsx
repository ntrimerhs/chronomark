import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CONSENT_EVENT } from '../lib/authFetch'
import { fetchConsents, saveConsent } from '../lib/consent'
import '../styles/authDialog.css'

/* Asks for the explicit consent GDPR art. 49(1)(a) requires before document
   text and questions are sent to DeepSeek (servers in China). Shown once after
   sign-in, and again whenever the API answers consent_required. */

export default function ConsentGate({ children }) {
  const [open, setOpen] = useState(false)
  const [marketing, setMarketing] = useState(false)
  const [agree, setAgree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const check = useCallback(async () => {
    try {
      const state = await fetchConsents()
      setOpen(!state?.china_transfer)
    } catch {
      /* API unreachable: the server still refuses processing without consent. */
    }
  }, [])

  useEffect(() => {
    check()
    const onNeeded = () => setOpen(true)
    window.addEventListener(CONSENT_EVENT, onNeeded)
    return () => window.removeEventListener(CONSENT_EVENT, onNeeded)
  }, [check])

  async function accept() {
    setBusy(true)
    setError('')
    try {
      await saveConsent('china_transfer', true)
      if (marketing) await saveConsent('marketing', true)
      setOpen(false)
    } catch {
      setError('Could not save your choice. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {children}
      {open ? (
        <div className="auth-backdrop" role="dialog" aria-modal="true" aria-labelledby="cm-consent-title">
          <div className="auth-card">
            <h2 id="cm-consent-title" style={{ margin: '0 0 12px', fontSize: 20 }}>Before you upload</h2>
            <p style={{ fontSize: 14, lineHeight: 1.55, color: '#c9ccd8' }}>
              To answer questions about your files, ChronoMark sends their text and your questions to
              DeepSeek, an AI provider whose servers are in <strong>China</strong>. The EU has no adequacy
              decision for China and we have no standard contractual clauses with the provider, so your
              data may be less protected there, and the provider decides how long it keeps it.
            </p>
            <p style={{ fontSize: 14, lineHeight: 1.55, color: '#c9ccd8' }}>
              Your uploaded files are deleted from ChronoMark after 4 hours. Do not upload other
              people&rsquo;s personal, medical or confidential data. See the{' '}
              <Link to="/privacy" target="_blank" style={{ color: '#a8a2ff' }}>Privacy Policy</Link>.
            </p>
            <label style={{ display: 'flex', gap: 10, margin: '14px 0', fontSize: 14, alignItems: 'flex-start' }}>
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
              <span>I explicitly consent to this transfer of my data to China. I can withdraw this in Settings at any time.</span>
            </label>
            <label style={{ display: 'flex', gap: 10, margin: '0 0 16px', fontSize: 13, alignItems: 'flex-start', color: '#a7acba' }}>
              <input type="checkbox" checked={marketing} onChange={(e) => setMarketing(e.target.checked)} />
              <span>Optional: send me product news and offers by email. Unsubscribe any time.</span>
            </label>
            {error ? <p style={{ color: '#ff8a8a', fontSize: 13 }}>{error}</p> : null}
            <button type="button" className="auth-submit" disabled={!agree || busy} onClick={accept}>
              <span>{busy ? 'Saving…' : 'Agree and continue'}</span>
            </button>
          </div>
        </div>
      ) : null}
    </>
  )
}
