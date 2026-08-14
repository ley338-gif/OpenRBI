import { useCallback, useEffect, useRef, useState } from "react";
import RFB from "@novnc/novnc";
import { StatusBadge } from "@shared/components/StatusBadge";
import { ErrorBanner } from "@shared/components/FormField";
import { PageHeader } from "@shared/components/PageHeader";
import { IconButton } from "@shared/components/IconButton";
import { EmptyState } from "@shared/components/States";
import { Icons } from "@shared/components/Icons";
import { useToast } from "@shared/components/Toast";
import type { SessionResponseDto, SessionStatus } from "@shared/api/types";
import { userApi, displayWebSocketUrl } from "../api/userApi";
import { ApiError } from "@shared/api/client";

const TERMINAL = new Set<SessionStatus>(["TERMINATED", "FAILED"]);
const CONNECTABLE = new Set<SessionStatus>(["ACTIVE", "DISCONNECTED"]);

// Comfort/UX only, not the security boundary — the real enforcement is at
// the relay's protocol level (app/api/display.py,
// app/core/rfb_clipboard_filter.py), which blocks ClientCutText/
// ServerCutText messages regardless of what this UI does. Hiding/ignoring
// these here just avoids offering a button or silently-dropped auto-sync
// that wouldn't actually do anything — a DevTools console bypassing this
// check would still hit the same relay-level block.
function canSendClipboard(mode: SessionResponseDto["clipboard_mode"]): boolean {
  return mode === "LOCAL_TO_REMOTE" || mode === "BIDIRECTIONAL_TEXT";
}
function canReceiveClipboard(mode: SessionResponseDto["clipboard_mode"]): boolean {
  return mode === "REMOTE_TO_LOCAL" || mode === "BIDIRECTIONAL_TEXT";
}

// Fallback only for the brief window before a session response has
// arrived — the real resolution comes from the session itself
// (session.screen_width/height), which reflects whatever the user's
// SESSION policy resolved to server-side (docs/policies.md), not a fixed
// sandbox constant anymore.
const DEFAULT_SANDBOX_WIDTH = 1280;
const DEFAULT_SANDBOX_HEIGHT = 800;

/** Largest box of `aspect` that fits inside (availW, availH) without
 * overflowing either dimension — a plain "contain fit", computed in JS
 * instead of via CSS aspect-ratio because that property only derives ONE
 * dimension from the other; combined with a max-height clamp it produced
 * a box wider than the sandbox's own ratio, which scaleViewport then
 * padded with black bars on the sides instead of actually filling it (a
 * real issue reported from a live session, not a hypothetical).
 */
function containFit(availW: number, availH: number, aspect: number): { width: number; height: number } {
  if (availW <= 0 || availH <= 0) return { width: 0, height: 0 };
  if (availW / availH > aspect) {
    return { width: Math.floor(availH * aspect), height: Math.floor(availH) };
  }
  return { width: Math.floor(availW), height: Math.floor(availW / aspect) };
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
  const [fitMode, setFitMode] = useState<"fit" | "native">("fit");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerCardRef = useRef<HTMLDivElement>(null);
  const viewerAreaRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const pollRef = useRef<number | null>(null);
  const liveRef = useRef<number | null>(null);
  const [boxSize, setBoxSize] = useState({ width: 960, height: 600 });
  const sandboxWidth = session?.screen_width ?? DEFAULT_SANDBOX_WIDTH;
  const sandboxHeight = session?.screen_height ?? DEFAULT_SANDBOX_HEIGHT;
  const sandboxAspect = sandboxWidth / sandboxHeight;

  // Recompute the viewer's exact pixel size whenever the card around it
  // resizes, so "Fit" always matches the sandbox's aspect ratio exactly
  // and scaleViewport has zero slack to fill with black bars — using the
  // full height and width the page layout actually gives this card,
  // instead of a fixed aspect-ratio/max-height pair that could disagree
  // with each other at some window sizes. In "native" mode the box is
  // just the sandbox's real resolution, and the area scrolls instead.
  useEffect(() => {
    const el = viewerCardRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      if (fitMode === "native") {
        setBoxSize({ width: sandboxWidth, height: sandboxHeight });
      } else {
        setBoxSize(containFit(entry.contentRect.width, entry.contentRect.height, sandboxAspect));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [session, fitMode, sandboxWidth, sandboxHeight, sandboxAspect]);

  useEffect(() => {
    if (rfbRef.current) rfbRef.current.scaleViewport = fitMode === "fit";
  }, [fitMode]);

  useEffect(() => {
    function onFsChange() {
      setIsFullscreen(document.fullscreenElement === viewerAreaRef.current);
    }
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else if (viewerAreaRef.current) {
      viewerAreaRef.current.requestFullscreen().catch(() => notify("Fullscreen isn't available in this browser.", "error"));
    }
  }

  async function sendClipboard() {
    if (!session || !canSendClipboard(session.clipboard_mode)) return;
    try {
      const text = await navigator.clipboard.readText();
      rfbRef.current?.clipboardPasteFrom(text);
      notify("Clipboard sent to the session");
    } catch {
      notify("Couldn't read your clipboard — check the browser's clipboard permission.", "error");
    }
  }

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

  const connectDisplay = useCallback(
    (sessionId: string, clipboardMode: SessionResponseDto["clipboard_mode"]) => {
      if (!containerRef.current || rfbRef.current) return;
      setConnectError(null);
      const rfb = new RFB(containerRef.current, displayWebSocketUrl(sessionId));
      // Scale the remote framebuffer to fill the viewer instead of
      // rendering it at the sandbox's native resolution in a corner of a
      // much larger container — real feedback: without this, most of the
      // card was empty black space around a small fixed-size canvas. Not
      // resizeSession: the sandbox's Xvfb resolution is fixed for the
      // lifetime of a session (set once at creation from the user's
      // SESSION policy, docs/policies.md) — there's no live resize path,
      // so asking the server to resize mid-session would just fail
      // silently; scaling the client-side canvas is the only real option
      // here.
      rfb.scaleViewport = fitMode === "fit";
      rfb.addEventListener("connect", () => {
        setRfbConnected(true);
        // The backend just flipped this session back to ACTIVE as a side
        // effect of accepting this connection — refetch so the status
        // badge reflects that instead of whatever it showed before
        // reconnecting.
        userApi.getSession(sessionId).then(setSession).catch(() => {});
      });
      rfb.addEventListener("disconnect", () => {
        setRfbConnected(false);
        rfbRef.current = null;
      });
      rfb.addEventListener("credentialsrequired", () => setConnectError("The remote display rejected the connection."));
      // Real, noVNC-native clipboard sync from the remote session back to
      // this device — only wired one direction automatically (remote ->
      // local); the other direction is the explicit "Send clipboard"
      // button above, since silently overwriting the user's own clipboard
      // on every keystroke would be surprising.
      rfb.addEventListener("clipboard", (e: Event) => {
        if (!canReceiveClipboard(clipboardMode)) return; // comfort-only guard, see canReceiveClipboard above
        const text = (e as CustomEvent<{ text: string }>).detail?.text;
        if (text) navigator.clipboard.writeText(text).catch(() => {});
      });
      rfbRef.current = rfb;
    },
    [fitMode],
  );

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
  }, [pollSession]);

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
      connectDisplay(session.id, session.clipboard_mode);
      watchLiveSession(session.id);
    } else {
      stopLiveWatch();
    }
  }, [session, connectDisplay, watchLiveSession, stopLiveWatch]);

  const busy = starting || (session && !TERMINAL.has(session.status) && session.status !== "ISOLATED" && !rfbConnected);
  const showViewer = session && !TERMINAL.has(session.status) && session.status !== "ISOLATED";

  return (
    <div className="page" style={{ display: "flex", flexDirection: "column" }}>
      <PageHeader
        title="Secure Browser"
        subtitle="Your isolated remote browser — nothing here ever reaches this device."
        actions={
          !showViewer && (
            <button type="button" className="btn btn-primary" onClick={() => void start()} disabled={starting}>
              {starting ? <span className="spinner" /> : null} Start Secure Browser
            </button>
          )
        }
      />

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

      {showViewer && (
        <div ref={viewerAreaRef} className="card" style={{ padding: 0, overflow: "hidden", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <div className="viewer-toolbar">
            <div className="viewer-toolbar-group">
              <StatusBadge value={session.status} />
              <span className="mono">{session.id.slice(0, 8)}</span>
              <span>Started {session.started_at ? new Date(session.started_at).toLocaleTimeString() : "—"}</span>
            </div>
            <div className="viewer-toolbar-group">
              <button
                type="button"
                className={`viewer-toolbar-toggle${fitMode === "fit" ? " active" : ""}`}
                onClick={() => setFitMode("fit")}
                aria-pressed={fitMode === "fit"}
              >
                Fit
              </button>
              <button
                type="button"
                className={`viewer-toolbar-toggle${fitMode === "native" ? " active" : ""}`}
                onClick={() => setFitMode("native")}
                aria-pressed={fitMode === "native"}
              >
                100%
              </button>
              <div className="viewer-toolbar-divider" />
              <IconButton
                label={canSendClipboard(session.clipboard_mode) ? "Send clipboard to session" : "Clipboard blocked by policy"}
                onClick={() => void sendClipboard()}
                disabled={!canSendClipboard(session.clipboard_mode)}
              >
                <Icons.Clipboard width={16} height={16} />
              </IconButton>
              <IconButton label={isFullscreen ? "Exit fullscreen" : "Fullscreen"} onClick={toggleFullscreen}>
                {isFullscreen ? <Icons.Minimize width={16} height={16} /> : <Icons.Maximize width={16} height={16} />}
              </IconButton>
              <div className="viewer-toolbar-divider" />
              <button type="button" className="btn btn-danger btn-sm" onClick={() => void endSession()}>
                End session
              </button>
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", position: "relative", overflow: "auto", background: "#000" }} ref={viewerCardRef}>
            {!rfbConnected && (
              <div className="loading-block" style={{ position: "absolute", zIndex: 1, width: "100%", color: "var(--color-slate-300)" }}>
                <span className="spinner" />
                {session.status === "QUEUED" && " Waiting for capacity…"}
                {session.status === "STARTING" && " Preparing sandbox…"}
                {CONNECTABLE.has(session.status) && " Connecting display…"}
              </div>
            )}
            <div ref={containerRef} style={{ width: boxSize.width, height: boxSize.height, flexShrink: 0, background: "#000" }} />
          </div>
        </div>
      )}

      {session?.status === "ACTIVE" && <UploadPanel sessionId={session.id} />}

      {!session && !starting && (
        <div className="card">
          <EmptyState icon={<Icons.Browser width={20} height={20} />} title="No active session">
            Start an isolated remote browser to browse the web safely — use the "Start Secure Browser" button above.
          </EmptyState>
        </div>
      )}

      <p className="text-muted" style={{ marginTop: "8px", fontSize: "0.8rem", flexShrink: 0 }}>
        {busy ? "Starting secure session…" : null}
      </p>
    </div>
  );
}
