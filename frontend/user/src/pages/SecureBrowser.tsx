import { useCallback, useEffect, useRef, useState } from "react";
import RFB from "@novnc/novnc";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ErrorBanner } from "@shared/components/FormField";
import { useToast } from "@shared/components/Toast";
import type { SessionResponseDto, SessionStatus } from "@shared/api/types";
import { userApi, displayWebSocketUrl } from "../api/userApi";
import { ApiError } from "@shared/api/client";

const TERMINAL = new Set<SessionStatus>(["TERMINATED", "FAILED"]);
const CONNECTABLE = new Set<SessionStatus>(["ACTIVE", "DISCONNECTED"]);

function UploadPanel({ sessionId }: { sessionId: string }) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload() {
    const file = inputRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      await userApi.uploadFile(sessionId, file);
      notify(`"${file.name}" allowed and transferred into your session`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        notify(`"${file.name}" blocked by policy`, "error");
      } else if (e instanceof ApiError && e.status === 413) {
        notify(`"${file.name}" is too large`, "error");
      } else {
        notify("Upload failed — scan may have failed or the backend is unavailable", "error");
      }
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="card">
      <h2 style={{ margin: "0 0 8px", fontSize: "1.1rem" }}>Upload a file into this session</h2>
      <div style={{ display: "flex", gap: "8px" }}>
        <input ref={inputRef} type="file" />
        <button type="button" className="btn btn-secondary" onClick={() => void handleUpload()} disabled={busy}>
          {busy ? <span className="spinner" /> : null} Upload
        </button>
      </div>
      <p className="hint">Every upload is hashed, type-detected, scanned, and policy-checked before it reaches the sandbox.</p>
    </div>
  );
}

/**
 * The core User Portal workflow (section 14/15): start a real sandbox,
 * follow its real lifecycle through to a live noVNC connection, and
 * surface every session state honestly — including ISOLATED, which is an
 * administrator action, not a connectivity glitch (section 16).
 */
export function SecureBrowser() {
  const { notify } = useToast();
  const [session, setSession] = useState<SessionResponseDto | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [rfbConnected, setRfbConnected] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const disconnectDisplay = useCallback(() => {
    rfbRef.current?.disconnect();
    rfbRef.current = null;
    setRfbConnected(false);
  }, []);

  const connectDisplay = useCallback((sessionId: string) => {
    if (!containerRef.current || rfbRef.current) return;
    setConnectError(null);
    const rfb = new RFB(containerRef.current, displayWebSocketUrl(sessionId));
    rfb.addEventListener("connect", () => setRfbConnected(true));
    rfb.addEventListener("disconnect", () => {
      setRfbConnected(false);
      rfbRef.current = null;
    });
    rfb.addEventListener("credentialsrequired", () => setConnectError("The remote display rejected the connection."));
    rfbRef.current = rfb;
  }, []);

  // Poll the session's real status (QUEUED -> STARTING -> ACTIVE, or a
  // failure/isolation transition) until it reaches ACTIVE/DISCONNECTED —
  // or a terminal state. The actual display connection is handled by the
  // effect below, once React has committed a render with the viewer div
  // in the DOM — calling connectDisplay directly from here would race
  // that commit and find containerRef.current still null (a real bug
  // caught during live testing: the very first "Start Secure Browser"
  // click never got past "Connecting display…", because the container
  // div only exists once `session` is already set in state).
  const pollSession = useCallback(
    (sessionId: string) => {
      stopPolling();
      pollRef.current = window.setInterval(async () => {
        try {
          const s = await userApi.getSession(sessionId);
          setSession(s);
          if (CONNECTABLE.has(s.status) || TERMINAL.has(s.status) || s.status === "ISOLATED") {
            stopPolling();
          }
        } catch {
          stopPolling();
          setConnectError("Lost contact with the server while starting the session.");
        }
      }, 1000);
    },
    [stopPolling],
  );

  const start = useCallback(async () => {
    setStartError(null);
    setStarting(true);
    try {
      const s = await userApi.startSession();
      setSession(s);
      if (!CONNECTABLE.has(s.status)) {
        pollSession(s.id);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setStartError("You already have a session running. End it before starting a new one.");
      } else if (e instanceof ApiError && e.status === 503) {
        setStartError("No browser capacity is available right now. Try again shortly.");
      } else {
        setStartError("Could not start a Secure Browser session. The backend may be unavailable.");
      }
    } finally {
      setStarting(false);
    }
  }, [connectDisplay, pollSession]);

  const endSession = useCallback(async () => {
    if (!session) return;
    stopPolling();
    // Terminate first, *then* close the display — not the reverse. Found
    // via live browser testing: closing the RFB connection first lets the
    // display WebSocket's own server-side close handler
    // (app/api/display.py) and this terminate call race as two concurrent
    // requests, and whichever's DB write lands last can silently overwrite
    // the session's status back to DISCONNECTED even though the sandbox
    // is already gone. Awaiting terminate first means the row is already
    // TERMINATED by the time the display connection closes, so that
    // handler's own `if session.status == ACTIVE` guard correctly skips
    // touching it — no backend change needed, just not racing it.
    try {
      const updated = await userApi.terminateSession(session.id);
      setSession(updated);
      notify("Session ended");
    } catch {
      notify("Could not end the session cleanly — it may already be gone.", "error");
    } finally {
      disconnectDisplay();
    }
  }, [session, disconnectDisplay, stopPolling, notify]);

  // On mount, pick up an already-running session (e.g. after a page reload).
  useEffect(() => {
    userApi
      .mySessions()
      .then((sessions) => {
        const live = sessions.find((s) => !TERMINAL.has(s.status) && s.status !== "ISOLATED");
        if (live) {
          setSession(live);
          if (!CONNECTABLE.has(live.status)) pollSession(live.id);
        }
      })
      .catch(() => {
        /* dashboard already surfaces backend-unavailable; this is a soft best-effort check */
      });
    return () => {
      stopPolling();
      disconnectDisplay();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Connects the display once the viewer div is actually in the DOM for a
  // connectable session — runs after React commits the render that made
  // containerRef non-null, never racing it.
  useEffect(() => {
    if (session && CONNECTABLE.has(session.status)) {
      connectDisplay(session.id);
    }
  }, [session, connectDisplay]);

  const busy = starting || (session && !TERMINAL.has(session.status) && session.status !== "ISOLATED" && !rfbConnected);

  return (
    <div className="page">
      <div className="flex-between">
        <div>
          <h1 style={{ marginBottom: 0 }}>Secure Browser</h1>
          {session && (
            <p className="text-muted" style={{ margin: "4px 0 0" }}>
              Session {session.id.slice(0, 8)} · <StatusBadge value={session.status} /> · started {" "}
              {session.started_at ? new Date(session.started_at).toLocaleTimeString() : "—"}
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: "8px" }}>
          {session && CONNECTABLE.has(session.status) ? (
            <button type="button" className="btn btn-danger" onClick={() => void endSession()}>
              End session
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={() => void start()} disabled={starting}>
              {starting ? <span className="spinner" /> : null} Start Secure Browser
            </button>
          )}
        </div>
      </div>

      {startError && <ErrorBanner>{startError}</ErrorBanner>}
      {connectError && <ErrorBanner>{connectError}</ErrorBanner>}

      {session?.status === "ISOLATED" && (
        <ErrorBanner>
          This session has been isolated by an administrator. Network access, uploads, and downloads are disabled.
          End this session and start a new one to continue browsing.
        </ErrorBanner>
      )}

      {session && TERMINAL.has(session.status) && (
        <div className="card">
          <p className="text-muted">
            {session.status === "FAILED"
              ? "This session failed to start or ended unexpectedly."
              : "This session has ended."}
          </p>
        </div>
      )}

      {session && !TERMINAL.has(session.status) && session.status !== "ISOLATED" && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {!rfbConnected && (
            <div className="loading-block" style={{ position: "absolute", zIndex: 1, width: "100%" }}>
              <span className="spinner" />
              {session.status === "QUEUED" && " Waiting for capacity…"}
              {session.status === "STARTING" && " Preparing sandbox…"}
              {CONNECTABLE.has(session.status) && " Connecting display…"}
            </div>
          )}
          <div
            ref={containerRef}
            style={{ width: "100%", aspectRatio: "16/10", background: "#000", minHeight: "480px" }}
          />
        </div>
      )}

      {session?.status === "ACTIVE" && <UploadPanel sessionId={session.id} />}

      {!session && !starting && (
        <div className="card">
          <p className="text-muted">No session yet. Click "Start Secure Browser" to open an isolated remote browser.</p>
        </div>
      )}

      <p className="text-muted" style={{ marginTop: "8px", fontSize: "0.8rem" }}>
        {busy ? "Starting secure session…" : null}
      </p>
    </div>
  );
}
