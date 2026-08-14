# Policies

> Status: implemented (Phase 12) — `app/services/policy_engine.py` (evaluation), `app/services/policies.py` (admin CRUD/versioning), `app/api/policies.py` (`/admin/policies/*`). Wired into the real download (Phase 13) and upload (Phase 16) pipelines — see [quarantine.md](quarantine.md) — and exercised directly via `evaluate_file_action` and its admin API.

## Roles vs. groups

Roles (`USER`, `SECURITY_REVIEWER`, `ADMIN`) grant **capabilities** in the product (what screens/actions are available). Groups are a separate concept and drive **security policy** (what a session is allowed to do: network, downloads, uploads, clipboard, browser, session limits, MIME/source rules). A user can belong to multiple groups; roles and groups are independent axes.

## Policy model

Policies are versioned. A published `PolicyVersion` is immutable — editing means creating a new draft version. Workflow: create draft → edit → publish → (further edits create a new version) → prior versions remain visible in history → rollback re-activates a prior published version as current. Every policy *decision* (a session's network permission, a file's action) records which `PolicyVersion` produced it.

A policy's `name` and `description` are metadata, not versioned content — `PUT /admin/policies/{id}` renames a policy or changes its description in place at any time (name must stay unique), independent of its versions. The `policy_type` itself is not editable after creation, since it determines which enforcement path (if any) a policy's content is read by.

When starting a new draft on a policy that already has a published version and no draft yet, the Admin Portal seeds the new draft's rows/content from that published version rather than starting blank — the published version itself stays immutable, but this makes "edit the live rules" a one-click action instead of requiring every existing rule to be retyped from scratch.

## Conflict model (deterministic)

When multiple applicable group policies disagree on a file rule, the outcome is decided by this fixed precedence — never by group ordering:

1. `DENY` wins over everything.
2. Otherwise `QUARANTINE` wins.
3. Otherwise `AUTO_RELEASE` wins.
4. Otherwise the default policy applies.

This ordering is deliberately conservative: any single group requiring denial or quarantine overrides a more permissive group the same user also belongs to.

## MIME and source matching

A file decision is never based on extension or HTTP `Content-Type` alone. Inputs considered: user, groups, source, declared MIME type, detected MIME type (magic bytes / actual file type), extension, file size, scanner result, and the policy version in force.

Source rules are normalized, not string-contains matched. A rule like `*.microsoft.com` must match `download.microsoft.com` and `office.microsoft.com`, but must **not** match `microsoft.com.attacker.org` or `evil-microsoft.com`. Matching is done against a parsed hostname's registrable-domain/subdomain structure, not substring search. Stored per download/upload: `initial_url`, `final_url`, `source_hostname`, `redirect_chain`, and whether TLS was used.

## What a Policy's `policy_type` actually does

`Policy.policy_type` (`NETWORK`, `DOWNLOADS`, `UPLOADS`, `CLIPBOARD`, `BROWSER`, `SESSION`, `MIME`, `SOURCE`) is a label chosen at creation time — the admin API (`app/api/policies.py`) accepts and stores it, and it's shown back in `PolicySummary`/`PolicyDetail`. Three types are read at decision time: `MIME`/`SOURCE` (via `FilePolicyRule` rows, below), `SESSION` (via its freeform `content` JSONB, below), and `CLIPBOARD` (via `content.clipboard_mode`, below). `NETWORK`/`DOWNLOADS`/`UPLOADS`/`BROWSER` are stored but have **zero runtime effect**.

Concretely, per the categories the project brief names:

- **Downloads/uploads (MIME/SOURCE rules)**: fully implemented and enforced — see [quarantine.md](quarantine.md). Final action is one of `AUTO_RELEASE`, `QUARANTINE`, `DENY`. `app/services/policy_engine.py`'s `evaluate_file_action` queries `FilePolicyRule` rows (which only ever have `rule_type` `MIME` or `SOURCE`) reachable through a user's groups, entirely independent of what `policy_type` the parent `Policy` was labeled with.
- **Session (screen resolution)**: implemented and enforced (Roadmap: resolution-per-policy). A published `SESSION`-type policy's `content` can carry `{"screen_width": <int>, "screen_height": <int>}` — set through the Admin Portal's Policy Detail page (an editor only shown for `SESSION`-type policies) rather than hand-edited JSON. `app/services/policy_engine.py`'s `resolve_session_resolution` reads this the same way `evaluate_file_action` reads file rules: every published `SESSION` policy attached (via a group) to the session's owner is a candidate. **Conflict model**: unlike file rules (`DENY` wins), there's no natural "more restrictive" resolution, so the **smallest pixel area wins** when more than one applies — consistent with never spending more of a node's resources than any single applicable policy asked for. No applicable policy (or a policy with missing/malformed `content`) falls back to the sandbox image's own default (1280×800, `docker/browser/entrypoint.sh`). The resolution is resolved once, at session creation (`app/services/sessions.py`'s `create_session`), and snapshotted onto the `BrowserSession` row (`screen_width`/`screen_height`) — it does not change for a session already running, even if the policy is edited afterward.
- **Network**: egress control is real and enforced, but as a single static blocklist applied to the whole `browser-plane` network (`scripts/setup-network-isolation.sh`, see [security-model.md](security-model.md#network-isolation)) — not per-group/per-policy. A `Policy` labeled `NETWORK` can be created and versioned through the admin API but has no effect; there is no per-group network policy enforcement in MVP 1.
- **Clipboard**: implemented and enforced at the **display relay's protocol level**, not just in the UI — see the dedicated section below.
- **Browser**: not implemented as enforced policy content — browser hardening is a fixed property of the sandbox image (docker/browser/). Session resource limits *other than resolution* (`max_sessions_per_user`, CPU/RAM/PID/disk) also still come from `.env`/request defaults, not from a versioned `Policy`.

This is a real, tracked gap for the remaining types, not a silent one: the data model and admin CRUD support all eight policy types uniformly (by design, so adding real enforcement for one later doesn't need a schema change), and `SESSION` (screen resolution), `CLIPBOARD`, and `MIME`/`SOURCE` are now enforced; creating a `NETWORK`/`DOWNLOADS`/`UPLOADS`/`BROWSER`-typed policy through the admin API today does not do anything beyond storing it.

## Clipboard enforcement (protocol-level, not UI-only)

A published `CLIPBOARD`-type policy's `content` carries `{"clipboard_mode": "<NONE|LOCAL_TO_REMOTE|REMOTE_TO_LOCAL|BIDIRECTIONAL_TEXT>"}`, set through the Admin Portal's Policy Detail page. `app/services/policy_engine.py`'s `resolve_clipboard_policy` reads this the same way `resolve_session_resolution` reads screen resolution — every published `CLIPBOARD` policy attached to the session owner's groups is a candidate, resolved once at session creation and snapshotted onto `BrowserSession.clipboard_mode` (same pattern as `screen_width`/`screen_height`: a later policy edit never retroactively changes a session already running). No applicable policy falls back to `BIDIRECTIONAL_TEXT` (today's pre-existing, unrestricted behavior).

**Conflict model**: a direction is only allowed in the resolved mode if *every* applicable `CLIPBOARD` policy allows it — one group's `NONE` beats another group's `BIDIRECTIONAL_TEXT`, and a group allowing only `LOCAL_TO_REMOTE` combined with another allowing only `REMOTE_TO_LOCAL` resolves to `NONE`, not to an arbitrary pick of one direction. Same conservative "any group that wants it locked down wins" principle as the file-rule conflict model above, just per direction instead of per fixed action ranking.

**Enforcement mechanism**: unlike the other "not enforced" types, this isn't UI-only. `app/api/display.py`'s WebSocket relay between the user's browser and the sandbox's VNC server feeds every byte through `app/core/rfb_clipboard_filter.py`, which recognizes RFB `ClientCutText`/`ServerCutText` messages in the byte stream and drops the ones the session's resolved `clipboard_mode` doesn't allow — before they ever reach the other side. This is real even against a user who bypasses the frontend UI entirely (e.g. via the browser DevTools console), because the control point is the relay, not the page.

The frontend (`frontend/user/src/pages/SecureBrowser.tsx`) additionally disables the "Send clipboard" button and ignores incoming clipboard sync when the resolved mode disallows that direction — this is comfort/UX only, explicitly commented as such in the code, not the security boundary.

**Why this couldn't just be full VNC protocol parsing** (see `app/core/rfb_clipboard_filter.py`'s module docstring for the full reasoning): the client→server RFB message set noVNC sends is small and fully enumerable with fixed/trivially length-prefixed framing, so that direction is always parsed and `ClientCutText` is dropped outright when required. The server→client direction carries `ServerCutText` interleaved with `FramebufferUpdate`, whose rectangle length depends on the negotiated pixel encoding (Raw, CopyRect, RRE, Hextile, Tight, ZRLE, ...) — reliably tracking message boundaries for the general case would mean reimplementing those encodings' framing, which this project deliberately avoids. Instead, **only when a session's resolved mode requires blocking `ServerCutText`** (`NONE` or `LOCAL_TO_REMOTE`), the relay rewrites the client's own `SetEncodings` message in flight to advertise only `Raw` and `CopyRect` — encodings with fixed, computable framing — before it reaches the sandbox's VNC server, making full server-stream parsing tractable. Sessions where `ServerCutText` stays allowed (`REMOTE_TO_LOCAL`, `BIDIRECTIONAL_TEXT` — the unconfigured default) get no rewrite and no server-stream parsing at all: pure byte passthrough, identical to the relay's pre-existing behavior.

**Documented trade-offs and residual risk, not silent**:
- Sessions with `ServerCutText` blocked lose server-side compression (more bandwidth) and remote cursor-shape updates (noVNC falls back to a local pointer) for the session's lifetime — an accepted cost of the encoding restriction, not a regression bug.
- **Fail-closed on any unrecognized framing**: if the relay ever encounters a byte sequence outside the bounded message set it understands (in either direction), it tears the connection down rather than guessing and risking a silent leak or a corrupted stream. This can also be triggered by a VNC server implementation that ignores the restricted `SetEncodings` list.
- This module can only act on RFB `CutText` messages. It does not defend against a sandboxed application exfiltrating clipboard-like data through some other channel entirely, and it does not defend against a malicious/non-compliant VNC server — a mismatch there surfaces as a torn-down connection, not a silent bypass, but it is not prevented outright.

## Example

A user in groups `finance` (DENY `.exe`) and `general` (AUTO_RELEASE all Office documents) downloads a `.exe` disguised with a `.docx` extension. Detected/magic-byte MIME shows an executable regardless of extension → `finance`'s `DENY` applies under the conflict model above, regardless of `general`'s more permissive rule.

**A specific `AUTO_RELEASE` rule losing to a broader rule in another group is expected, not a bug.** A user in group `pdf-reviewers` has a published `MIME` policy with a single rule `application/pdf → AUTO_RELEASE`. The same user is also in `default-users`, whose published `MIME` policy has a broader rule `application/* → QUARANTINE` (a common "catch-all for this whole category, allow only what's explicitly cleared" pattern). Downloading a PDF matches both rules — `application/pdf` and `application/*` — and per the conflict model, `QUARANTINE` beats `AUTO_RELEASE` regardless of which rule is more specific or which group is "more relevant" to the file. The file lands in quarantine even though `pdf-reviewers`' own rule says otherwise. This is not evaluated by rule specificity, only by the action each matching rule carries — an admin who wants PDFs from `pdf-reviewers` to actually auto-release must either remove the user from any group with a broader/stricter catch-all rule, or narrow that catch-all rule to exclude `application/pdf`.

A user in groups `design` (a published `SESSION` policy with `{"screen_width": 1920, "screen_height": 1080}`) and `field-ops` (a published `SESSION` policy with `{"screen_width": 1024, "screen_height": 768}`) starts a Secure Browser session → the smallest-area rule applies, so the sandbox comes up at 1024×768, not 1920×1080.
