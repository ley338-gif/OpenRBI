# Quarantine

> Status: Phases 13–15 are all implemented: download interception/staging/hashing/MIME detection/policy pre-check, real ClamAV scanning with a fail-closed final decision, and the admin release/reject review workflow plus single-use download tokens. A real quarantine-storage abstraction beyond local disk staging (content-addressed but not yet pluggable/S3-like) remains a known simplification, not a functional gap — see [architecture.md](architecture.md).

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

## Scanning and the final decision (Phase 14)

`app/core/clamav_client.py` speaks clamd's native protocol directly over TCP (`PING`/`VERSION`/`INSTREAM`) rather than pulling in a third-party client library, so every failure mode is under explicit control. `app/services/scanning.py`'s `scan_and_finalize` applies the fail-closed rules from [ADR 0008](adr/0008-fail-closed.md):

| Scan result | Policy pre-check | Final `QuarantineFile.status` |
|---|---|---|
| scanner unreachable/error | *(any)* | `QUARANTINED` — never released regardless of policy |
| infected | *(any)* | `QUARANTINED` + `MALWARE_DETECTED` event + a `CRITICAL` Incident (§21's automatic-incident list) — never silently deleted, kept for review |
| clean | `DENY` | `REJECTED` immediately (§16 step 11: "löschen/blockieren" — policy already decided, no human review needed) |
| clean | `QUARANTINE` (or no policy matched) | `QUARANTINED`, awaiting admin review — release/reject mechanics are Phase 15 |
| clean | `AUTO_RELEASE` | `RELEASED` — the row is marked cleared; the actual single-use download token for user retrieval is Phase 15 |

Verified against the live stack: the standard EICAR test string is correctly flagged infected (`Eicar-Test-Signature`) and forced to `QUARANTINED` with a `CRITICAL` incident *even when its policy verdict was `AUTO_RELEASE`* — malware detection overrides policy, never the reverse. Also verified the fail-closed case directly: stopping the ClamAV container and re-running the same `AUTO_RELEASE`-eligible file correctly produces `QUARANTINED`/`ERROR`, not a release.

## Review and release (Phase 15)

Admin/Security Reviewer (`app/api/admin_quarantine.py`, `POST /admin/quarantine/{id}/{release,reject}`) can only act on a file still in `QUARANTINED` — a file already `RELEASED` (including via Phase 14's auto-release) or `REJECTED` is not re-actionable through this path, closing off double-release/release-after-reject races. Both roles can review, matching §6's explicit `SECURITY_REVIEWER` right to release/reject files. Every decision records `reviewed_at`/`reviewed_by`/`review_comment` and emits `FILE_RELEASED`/`FILE_REJECTED`. The file itself is never opened or previewed by the reviewer — only its captured metadata (hash, source, MIME, scan status) is shown, per §19.

A `RELEASED` file (whether auto-released or manually released) isn't handed to the user directly — `app/core/release_tokens.py` issues a time-limited (5 minute), single-use token via Redis `GETDEL` (atomic get-and-delete, so there's no window where concurrent requests could both consume the same token). `GET /files/download/{token}` requires both a valid, unconsumed token *and* that the requesting session's user matches the token's owner — an unknown, expired, already-used, or wrong-owner token all fail identically with a generic `401` (§20: never confirm to a caller that a valid token exists for someone else). `GET /files/me` and `POST /files/{id}/download-token` use the same ownership check as sessions and the display websocket (`app/api/sessions.py`, `app/api/display.py`): a file belonging to someone else is a `404`, indistinguishable from a nonexistent one — verified directly, including against an ADMIN account (role doesn't grant implicit ownership).

Verified end-to-end against the live stack: a reviewer lists and releases a `QUARANTINED` file; re-releasing it is correctly rejected (`409`); a plain `USER` is blocked from every `/admin/quarantine` endpoint (`403`); the owning user requests a token, downloads the exact file content, and a second attempt with the *same* token correctly fails (`401`); a different user (even an ADMIN) cannot obtain a token for someone else's file (`404`).

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
