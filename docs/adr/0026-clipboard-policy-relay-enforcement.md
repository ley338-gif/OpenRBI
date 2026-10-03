# ADR 0022: Clipboard policy enforcement at the RFB relay, not full protocol parsing

## Status

Accepted

## Context

`docs/policies.md` documented `CLIPBOARD` as a policy type with no runtime effect at all: the four intended modes (`NONE`/`LOCAL_TO_REMOTE`/`REMOTE_TO_LOCAL`/`BIDIRECTIONAL_TEXT`) were stored but never read. The only existing "clipboard denied" behavior was a side effect of `isolate_session`'s full network-disconnect primitive, not a dedicated control usable during a normal `ACTIVE` session.

`app/api/display.py`'s WebSocket relay between the user's browser (noVNC) and the sandbox's VNC server does pure byte-for-byte forwarding in both directions today, with zero message parsing. A real, per-group clipboard control has to intercept RFB `ClientCutText`/`ServerCutText` messages somewhere in that stream — a UI-only control (hiding the "Send clipboard" button, ignoring the `clipboard` event) is trivially bypassed via the browser DevTools console and does not meet this project's fail-closed bar for a security control.

The obstacle: `ServerCutText` (sandbox → user direction) is interleaved with `FramebufferUpdate` messages, whose rectangle payload length depends on the negotiated pixel encoding (Raw, CopyRect, RRE, Hextile, Tight, ZRLE, ...). Reliably finding message boundaries in that stream for the general case requires understanding every encoding's framing — effectively reimplementing significant parts of the RFB/VNC protocol, which this project has consistently avoided taking on (see ADR-0009's reasoning for choosing noVNC precisely because it's a thin, easy-to-reason-about client).

## Decision

Enforce clipboard policy at the relay's protocol level using a scoped, real parser (`app/core/rfb_clipboard_filter.py`) rather than a full RFB implementation:

- **Client→server direction** (`ClientCutText`): always fully parsed. noVNC's client→server message set is small and fully enumerable, with fixed or trivially length-prefixed framing (`SetPixelFormat`, `SetEncodings`, `FramebufferUpdateRequest`, `KeyEvent`, `PointerEvent`, `ClientCutText`, and a handful of extension messages). `ClientCutText` is dropped outright when the session's resolved mode doesn't allow that direction.
- **Server→client direction** (`ServerCutText`): only parsed when the resolved mode requires blocking it (`NONE`/`LOCAL_TO_REMOTE`). In that case, the relay rewrites the client's own `SetEncodings` message in flight to advertise only `Raw`(0) and `CopyRect`(1) — the two pixel encodings with fixed, computable rectangle lengths — before it reaches the sandbox's VNC server. This makes tracking `FramebufferUpdate` message boundaries tractable without decoding pixel data or reimplementing compressed encodings. When the resolved mode allows `ServerCutText` (`REMOTE_TO_LOCAL`, `BIDIRECTIONAL_TEXT` — the unconfigured default), the server→client direction is untouched: pure byte passthrough, identical to the pre-existing relay.
- **Fail-closed**: any byte sequence outside the bounded framing this module understands raises `RfbProtocolError`, and the relay tears the connection down rather than forwarding a byte sequence it can't confidently classify.
- Resolved once at session creation (`resolve_clipboard_policy`, mirroring `resolve_session_resolution`'s pattern) and snapshotted onto `BrowserSession.clipboard_mode` — a later policy edit never retroactively changes a session already running.
- The frontend additionally disables the "Send clipboard" button and ignores incoming clipboard sync when the resolved mode disallows that direction, explicitly as comfort/UX, not the security boundary.

## Alternatives Considered

- **Full RFB/VNC protocol parser for both directions** — rejected. Reimplementing every pixel encoding's framing (and keeping it correct as noVNC/x11vnc versions change) is exactly the scope this project has avoided by choosing noVNC's thin client in the first place (ADR-0009). High implementation and maintenance cost for a single policy dimension.
- **UI-only control (hide/disable the button, ignore the event)** — rejected as the *primary* mechanism, since it does nothing against a user who bypasses the page (DevTools console, a custom noVNC-compatible client). Kept as defense-in-depth on top of the real relay-level control.
- **Reconfigure/restrict the sandbox's VNC server (x11vnc) directly** — rejected. There's no portable, standard RFB capability to have the server unilaterally suppress `CutText` messages per-connection, and this would couple clipboard policy to VNC-server-specific configuration rather than the per-session policy resolution this project's other enforced policy types already use.
- **Always restrict SetEncodings to Raw/CopyRect for every session** — rejected. This would impose the bandwidth/cursor-shape cost on every session regardless of whether its clipboard policy actually needs server-stream parsing. Scoping the rewrite to only the sessions that need `ServerCutText` blocked keeps the common, unrestricted case (`BIDIRECTIONAL_TEXT`, the default) at zero added cost or risk.

## Consequences

- Sessions with `ServerCutText` blocked (`NONE`, `LOCAL_TO_REMOTE`) lose server-side pixel compression (higher bandwidth) and remote cursor-shape updates (noVNC falls back to a local pointer) for the session's lifetime — a real, accepted, documented cost of the encoding restriction, not a silent regression.
- Residual risk, explicitly not eliminated: this control only recognizes RFB `CutText` messages. It does not defend against a sandboxed application exfiltrating clipboard-like data through some other channel, and it does not defend against a malicious/non-compliant VNC server ignoring the restricted encoding list — a mismatch there surfaces as a torn-down connection (fail-closed), not a silent bypass.
- Follow-up work this does *not* attempt: `NETWORK`/`DOWNLOADS`/`UPLOADS`/`BROWSER` policy types remain stored-but-unenforced, unchanged by this ADR.
