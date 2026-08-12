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

// Matches the sandbox's actual Xvfb resolution (1280x800,
// docker/browser/entrypoint.sh) exactly.
const SANDBOX_ASPECT = 1280 / 800;

/** Largest box of SANDBOX_ASPECT that fits inside (availW, availH) without
 * overflowing either dimension — a plain "contain fit", computed in JS
 * instead of via CSS aspect-ratio because that property only derives ONE
 * dimension from the other; combined with a max-height clamp it produced
 * a box wider than the sandbox's own ratio, which scaleViewport then
 * padded with black bars on the sides instead of actually filling it (a
 * real issue reported from a live session, not a hypothetical).
 */
function containFit(availW: number, availH: number): { width: number; height: number } {
  if (availW <= 0 || availH <= 0) return { width: 0, height: 0 };
  if (availW / availH > SANDBOX_ASPECT) {
    return { width: Math.floor(availH * SANDBOX_ASPECT), height: Math.floor(availH) };
  }
  return { width: Math.floor(availW), height: Math.floor(availW / SANDBOX_ASPECT) };
}

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
  const viewerCardRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const pollRef = useRef<number | null>(null);
  const liveRef = useRef<number | null>(null);
  const [boxSize, setBoxSize] = useState({ width: 960, height: 600 });

  // Recompute the viewer's exact pixel size whenever the card around it
  // resizes, so the box always matches the sandbox's aspect ratio exactly
  // and scaleViewport has zero slack to fill with black bars — using the
  // full height and width the page layout actually gives this card,
  // instead of a fixed aspect-ratio/max-height pair that could disagree
  // with each other at some window sizes.
  useEffect(() => {
    const el = viewerCardRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setBoxSize(containFit(entry.contentRect.width, entry.contentRect.height));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [session]);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const stopLiveWatch = useCallback(() => {
    if (liveRef.current !== null) {
      window.clearInterval(liveRef.current);
      liveRef.current = null;
    }
  }, []);

  // Once a session is connectable, the display websocket itself drives
  // ACTIVE <-> DISCONNECTED transitions server-side (app/api/display.py) —
  // but nothing was ever refetching that status client-side afterward, so
  // the badge could get stuck showing "DISCONNECTED" from before a
  // reconnect indefinitely, even while the viewer was live and working (a
  // real bug reported from an actual session, not a timing hunch). This
  // also picks up an admin Isolate promptly instead of only on next page
  // load.
  const watchLiveSession = useCallback(
    (sessionId: string) => {
      stopLiveWatch();
      liveRef.current = window.setInterval(async () => {
        try {
          const s = await userApi.getSession(sessionId);
          setSession(s);
          if (TERMINAL.has(s.status) || s.status === "ISOLATED") stopLiveWatch();
        } catch {
          /* transient — the next tick retries; a real outage already
             surfaces via the RFB connection dropping */
        }
      }, 5000);
    },
    [stopLiveWatch],
  );

  const disconnectDisplay = useCallback(() => {
    rfbRef.current?.disconnect();
    rfbRef.current = null;
    setRfbConnected(false);
  }, []);

  const connectDisplay = useCallback((sessionId: string) => {
    if (!containerRef.current || rfbRef.current) return;
    setConnectError(null);
    const rfb = new RFB(containerRef.current, displayWebSocketUrl(sessionId));
    // Scale the remote framebuffer to fill the viewer instead of rendering
    // it at the sandbox's native resolution in a corner of a much larger
    // container — real feedback: without this, most of the card was empty
    // black space around a small fixed-size canvas. Not resizeSession: the
    // sandbox's Xvfb resolution is fixed server-side, so asking the server
    // to resize would just fail silently; scaling the client-side canvas
    // is the only real option here.
    rfb.scaleViewport = true;
    rfb.addEventListener("connect", () => {
      setRfbConnected(true);
      // The backend just flipped this session back to ACTIVE as a side
      // effect of accepting this connection — refetch so the status badge
      // reflects that instead of whatever it showed before reconnecting.
      userApi.getSession(sessionId).then(setSession).catch(() => {});
    });
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
      stopLiveWatch();
      disconnectDisplay();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Connects the display once the viewer div is actually in the DOM for a
  // connectable session — runs after React commits the render that made
  // containerRef non-null, never racing it. Also (re)starts the live status
  // watch for as long as the session stays connectable, and stops it once
  // the session leaves that state (terminated/isolated) so it doesn't keep
  // polling a session nobody can act on anymore.
  useEffect(() => {
    if (session && CONNECTABLE.has(session.status)) {
      connectDisplay(session.id);
      watchLiveSession(session.id);
    } else {
      stopLiveWatch();
    }
  }, [session, connectDisplay, watchLiveSession, stopLiveWatch]);

  const busy = starting || (session && !TERMINAL.has(session.status) && session.status !== "ISOLATED" && !rfbConnected);

  return (
    <div className="page" style={{ display: "flex", flexDirection: "column" }}>
      <div className="flex-between" style={{ flexShrink: 0 }}>
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
        <div
          ref={viewerCardRef}
          className="card"
          style={{
            padding: 0,
            overflow: "hidden",
            flex: 1,
            minHeight: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            position: "relative",
          }}
        >
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
            // Explicit pixel size from the containFit() calculation above —
            // always exactly the sandbox's own aspect ratio, sized to use
            // the full width or full height of this card (whichever is the
            // binding constraint), so scaleViewport fills it completely
            // with no black bars on any side.
            style={{ width: boxSize.width, height: boxSize.height, background: "#000" }}
          />
        </div>
      )}

      {session?.status === "ACTIVE" && <UploadPanel sessionId={session.id} />}

      {!session && !starting && (
        <div className="card">
          <p className="text-muted">No session yet. Click "Start Secure Browser" to open an isolated remote browser.</p>
        </div>
      )}

      <p className="text-muted" style={{ marginTop: "8px", fontSize: "0.8rem", flexShrink: 0 }}>
        {busy ? "Starting secure session…" : null}
      </p>
    </div>
  );
}
