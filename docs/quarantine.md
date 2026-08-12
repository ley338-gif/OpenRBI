# Quarantine

> Status: Phase 13 (download interception, staging, hashing, MIME detection, policy pre-check) is implemented. Every file lands in `PENDING_SCAN` and stays there — Phase 14 (real scanning) and Phase 15 (release/reject, real quarantine storage) are not yet built, so nothing is ever auto-released yet.

## How download interception actually works (Phase 13)

Firefox inside the sandbox is configured (`docker/browser/entrypoint.sh`, a `user.js` written at container start) to silently auto-save every download to a fixed directory (`$HOME/downloads`) with no save-as prompt — an isolated session has nowhere sensible to show that dialog, and the real control point is the policy engine downstream, not a client-side prompt.

The backend cannot reach into the sandbox's filesystem or network directly (docs/adr/0005) — only the Session Agent can, via the Docker API, which already manages the sandbox's lifecycle. The Session Agent exposes:

- `GET /v1/sandboxes/{id}/downloads` — lists completed downloads (anything without Firefox's in-progress `.part` suffix), via `find` through `exec`.
- `GET /v1/sandboxes/{id}/downloads/{filename}` — returns the file's bytes, plus a best-effort origin URL.
- `DELETE /v1/sandboxes/{id}/downloads/{filename}` — removes it from the sandbox after staging.

**Important implementation detail:** these read/fetch operations use `exec` (`cat`, `getfattr`), not Docker's archive API (`get_archive`/`docker cp`). The download directory lives under the tmpfs mount at `/tmp` (the container hardening baseline, docs/security-model.md), and Docker's archive API — which reads through the storage driver's layer-diff mechanism — cannot see files inside a tmpfs mount at all. This was confirmed empirically: even a plain `docker cp` from the host failed with "could not find the file" for a file that unmistakably existed. `exec` reads through a live process in the container's own mount namespace instead, which has no such limitation.

The backend runs a per-session background poll loop (`app/core/download_poller.py`, started when a session becomes `ACTIVE`) that, every few seconds, asks the Session Agent for new completed downloads and for each one:

1. Fetches the bytes.
2. Computes SHA-256 and size.
3. Detects the actual MIME type via magic bytes (`python-magic`/`libmagic1`) — **never** the filename extension. Verified directly: a file named `report.txt` containing a PNG signature was correctly detected as *not* `text/plain`.
4. Recovers a best-effort origin URL: Firefox on Linux (GIO/XDG convention) tags downloaded files with a `user.xdg.origin.url` extended attribute, read via `getfattr`. This is the **known gap** — it gives the final URL the browser actually fetched, not a full initial→final redirect chain, and no explicit "was this hop over TLS" signal beyond inferring it from the URL's scheme. Full redirect-chain capture would need deeper browser instrumentation (e.g. a WebExtension); tracked, not built.
5. Runs the Phase 12 policy engine (`evaluate_file_action`) as a **pre-check** using detected MIME/extension/size/source-hostname — this is not the final decision (no scanner exists yet), just what governs today's `PENDING_SCAN` outcome.
6. Stages the bytes locally, content-addressed by SHA-256 (`app/services/downloads.py:_stage_file`) — never under the original filename. Interim: Phase 15 replaces this with a real quarantine-storage abstraction.
7. Creates a `QuarantineFile` row (`status=PENDING_SCAN`) and a `DOWNLOAD_REQUESTED` security event.
8. Deletes the file from the sandbox. If that delete fails, the same content is deduplicated by SHA-256 on the next poll rather than creating a second row.

Verified end-to-end against the real running stack, including the tmpfs/archive-API limitation above and the getfattr stderr-concatenation bug both being real bugs caught and fixed during testing, not assumed correct.

## Download pipeline

1. Download detected inside the browser session.
2. File lands in a per-session staging area (not directly reachable by the client).
3. File size determined.
4. SHA-256 computed.
5. Declared MIME type captured (from the browser/HTTP response).
6. Actual file type detected (magic bytes), independent of the declared type and extension.
7. Source/URL metadata captured: `initial_url`, `final_url`, `source_hostname`, `redirect_chain`, TLS-used flag.
8. Policy pre-check.
9. File scanned (ClamAV via the `FileScanner` provider).
10. Final policy decision made, using scan result + all metadata above + the active `PolicyVersion`.
11. File is auto-released, quarantined, or deleted/blocked.
12. Security Events emitted at each meaningful step (`DOWNLOAD_REQUESTED`, `DOWNLOAD_BLOCKED`, `FILE_QUARANTINED`, `MALWARE_DETECTED`, etc.).

Fail-closed at every step — see [ADR 0008](adr/0008-fail-closed.md): scanner unavailable → no auto-release; policy engine error → no release; unknown file type → quarantine; quarantine storage unavailable → downloads blocked entirely.

## Quarantine storage

Quarantined files are **never** stored under their original filename on disk. Storage is content-addressed / keyed by an internal object ID, with all descriptive metadata held separately in the database:

`id (UUID)`, `session`, `user`, `original_name`, `extension`, `declared_mime`, `detected_mime`, `size`, `sha256`, `initial_url`, `final_url`, `source_host`, `redirect_chain`, `scanner_status`, `scanner_result`, `policy_action`, `status`, `storage_object_id`, `created_at`, `reviewed_at`, `reviewed_by`, `review_comment`.

### Status

`PENDING_SCAN → SCANNING → QUARANTINED → (RELEASED | REJECTED | DELETED)`

### Reviewer actions

`RELEASE`, `REJECT` — restricted to ADMIN/SECURITY_REVIEWER. A quarantined file is never automatically opened in the admin's own browser; file preview is explicitly out of scope for MVP 1.

## Release workflow

On `RELEASE`:

1. Check the reviewer's permissions.
2. Check the reviewer's own session/MFA is still valid.
3. Capture a review reason/comment.
4. Emit a `FILE_RELEASED` audit event.
5. Issue a time-limited download token.
6. Token is single-use.
7. The original requesting user retrieves the file using that token.

A release token cannot be replayed after first use or after expiry — both are enforced server-side, not just by hiding the download link in the UI.

## Upload pipeline

1. User selects a local file in the client browser.
2. File goes to the OpenRBI Upload Gateway (not a direct mount into the sandbox).
3. Hashing.
4. File-type detection.
5. Scan.
6. Policy check.
7. Temporary, scoped availability inside the sandbox.
8. Upload proceeds from the sandbox to the destination website.

## No "safe" claims

Status wording is limited to what was actually verified: *No threat detected*, *Scan completed*, *Policy allowed*, *Quarantined* — never "this file is safe."
