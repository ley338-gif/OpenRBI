import { useRef, useState } from 'react'
import RFB from '@novnc/novnc'

/**
 * Manual test harness for Phase 8 (noVNC remote display). The real
 * "Secure Browser" start button — which creates a BrowserSession and asks
 * the Session Agent to provision a sandbox before connecting — lands with
 * Phase 10/11's session lifecycle wiring. Until then, this connects to a
 * sandbox session id that already exists (created via the session-agent
 * API directly), to prove the noVNC relay path end-to-end.
 */
function SecureBrowserTest() {
  const [sessionId, setSessionId] = useState('')
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle')
  const containerRef = useRef<HTMLDivElement>(null)
  const rfbRef = useRef<RFB | null>(null)

  const connect = () => {
    if (!containerRef.current || !sessionId) return
    setStatus('connecting')

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/api/display/${sessionId}/ws`

    const rfb = new RFB(containerRef.current, url)
    rfb.addEventListener('connect', () => setStatus('connected'))
    rfb.addEventListener('disconnect', () => setStatus('idle'))
    rfb.addEventListener('credentialsrequired', () => setStatus('error'))
    rfbRef.current = rfb
  }

  const disconnect = () => {
    rfbRef.current?.disconnect()
    rfbRef.current = null
    setStatus('idle')
  }

  return (
    <section style={{ padding: '1rem' }}>
      <h2>Secure Browser (Phase 8 test harness)</h2>
      <p>
        Connects to an already-running sandbox session by id. The real start flow (create session,
        launch sandbox, then connect) is Phase 10/11 work.
      </p>
      <input
        placeholder="session id"
        value={sessionId}
        onChange={(e) => setSessionId(e.target.value)}
        disabled={status === 'connecting' || status === 'connected'}
      />
      {status === 'connected' ? (
        <button onClick={disconnect}>Disconnect</button>
      ) : (
        <button onClick={connect} disabled={!sessionId || status === 'connecting'}>
          Connect
        </button>
      )}
      <p>status: {status}</p>
      <div ref={containerRef} style={{ width: 1280, height: 800, background: '#000' }} />
    </section>
  )
}

export default SecureBrowserTest
