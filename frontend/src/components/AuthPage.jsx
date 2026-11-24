import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import AuthForm from './AuthForm'
import useAuth from '../hooks/useAuth'
import '../styles/authDialog.css'

/* /register and /login, as real pages.

   Same form as the header dialog, with room to breathe: this is where Get
   Started sends someone, so it has to stand on its own -- the header, a line
   about what the account is for, and the form. */

export default function AuthPage({ mode = 'signup' }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { session, ready } = useAuth()
  const [variant, setVariant] = useState(mode)

  const next = params.get('next') || '/upload'

  useEffect(() => {
    setVariant(mode)
  }, [mode])

  // Already signed in: nothing to fill in.
  useEffect(() => {
    if (ready && session) navigate(next, { replace: true })
  }, [ready, session, navigate, next])

  const signup = variant === 'signup'

  return (
    <main className="auth-page">
      <div className="auth-page-plate" aria-hidden="true" />

      <a className="auth-page-brand" href="/">
        <span>CHRONOMARK</span>
        <i />
      </a>

      <section className="auth-page-card">
        <div className="auth-head">
          <span className="auth-mark" aria-hidden="true">
            <span className="auth-mark-dot" />
          </span>
          <h2>{signup ? 'Create your account' : 'Welcome back'}</h2>
          <p>
            {signup
              ? 'One account for every document and every recording you analyse.'
              : 'Sign in to your workspaces.'}
          </p>
        </div>

        <AuthForm
          mode={variant}
          compact={false}
          onModeChange={(next) => {
            setVariant(next)
            navigate(next === 'signup' ? '/register' : '/login', { replace: true })
          }}
          onSuccess={() => navigate(next, { replace: true })}
        />
      </section>

      <p className="auth-page-foot">
        {signup ? 'Already have an account?' : 'No account yet?'}{' '}
        <a href={signup ? '/login' : '/register'}>{signup ? 'Sign in' : 'Create one'}</a>
      </p>
    </main>
  )
}
