# Quarantine

> Status: design reference for Phases 13–15 (Download Interception, File Scanner, Quarantine). Not yet implemented — see [development.md](development.md).

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
