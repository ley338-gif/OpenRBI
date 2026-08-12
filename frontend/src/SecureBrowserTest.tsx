import { useRef, useState } from 'react'
import RFB from '@novnc/novnc'

type SessionStatus = 'idle' | 'starting' | 'connecting' | 'connected' | 'error'

/**
 * The real "start a Secure Browser" flow (project brief §26: Login -> MFA
 * -> Secure Browser starten), wired to the actual session lifecycle
 * (POST /sessions) rather than a manually-typed session id. Admin session
 * control (disconnect/isolate/kill someone else's session) is Phase 11 and
 * lives in the admin portal, not here.
 */
function SecureBrowserTest() {
  const [status, setStatus] = useState<SessionStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const rfbRef = useRef<RFB | null>(null)
  const sessionIdRef = useRef<string | null>(null)

  const start = async () => {
    setError(null)
    setStatus('starting')
    try {
      const r = await fetch('/api/sessions', { method: 'POST', credentials: 'include' })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail || `failed to start session (${r.status})`)
      }
      const session = await r.json()
      sessionIdRef.current = session.id
      connectDisplay(session.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('error')
    }
  }

  const connectDisplay = (sessionId: string) => {
    if (!containerRef.current) return
    setStatus('connecting')
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/api/display/${sessionId}/ws`
    const rfb = new RFB(containerRef.current, url)
    rfb.addEventListener('connect', () => setStatus('connected'))
    rfb.addEventListener('disconnect', () => setStatus('idle'))
    rfb.addEventListener('credentialsrequired', () => setStatus('error'))
    rfbRef.current = rfb
  }

  const stop = async () => {
    rfbRef.current?.disconnect()
    rfbRef.current = null
    const sessionId = sessionIdRef.current
    if (sessionId) {
      await fetch(`/api/sessions/${sessionId}/terminate`, { method: 'POST', credentials: 'include' }).catch(() => {})
    }
    sessionIdRef.current = null
    setStatus('idle')
  }

  const busy = status === 'starting' || status === 'connecting' || status === 'connected'

  return (
    <section style={{ padding: '1rem' }}>
      <h2>Secure Browser</h2>
      {status === 'connected' || status === 'connecting' ? (
        <button onClick={stop}>End session</button>
      ) : (
        <button onClick={start} disabled={busy}>
          Start Secure Browser
        </button>
      )}
      <p>status: {status}</p>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <div ref={containerRef} style={{ width: 1280, height: 800, background: '#000' }} />
    </section>
  )
}

export default SecureBrowserTest
