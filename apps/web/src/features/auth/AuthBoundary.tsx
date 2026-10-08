import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '../../lib/api/client'
import type { AuthMe } from '../../lib/api/types'

export function AuthBoundary({ children }: { children: (authData: AuthMe) => React.ReactNode }) {
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    const expire = () => setSessionExpired(true)
    window.addEventListener('ares:auth-expired', expire)
    return () => window.removeEventListener('ares:auth-expired', expire)
  }, [])

  const auth = useQuery({ queryKey: ['auth-me'], queryFn: api.me, retry: false, staleTime: 30_000 })

  if (auth.isPending) {
    return <main className="auth-gate"><div className="auth-card"><div className="brand-mark">A</div><h1>ARES</h1><p>Loading your research workspace…</p></div></main>
  }

  if (sessionExpired || (auth.error instanceof ApiError && auth.error.status === 401)) {
    const returnPath = `${window.location.pathname}${window.location.search}`
    return (
      <main className="auth-gate">
        <section className="auth-card">
          <div className="brand-mark">A</div>
          <div className="eyebrow">Autonomous Research & Evidence System</div>
          <h1>Research you can trace back.</h1>
          <p>Your session is missing or expired. Sign in again through the configured identity provider to continue. Unsaved local composer text is not sent anywhere.</p>
          <a className="auth-signin" href={`/api/v1/auth/login?return_path=${encodeURIComponent(returnPath)}`}>Sign in to ARES</a>
        </section>
      </main>
    )
  }

  if (auth.isError || !auth.data) {
    return (
      <main className="auth-gate">
        <section className="auth-card">
          <AlertTriangle size={22}/>
          <h1>ARES could not start</h1>
          <p>{auth.error instanceof Error ? auth.error.message : 'Authentication bootstrap failed.'}</p>
          <button className="auth-signin" onClick={() => void auth.refetch()}>Retry</button>
        </section>
      </main>
    )
  }

  return <>{children(auth.data)}</>
}
