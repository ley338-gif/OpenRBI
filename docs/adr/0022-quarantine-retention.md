# ADR 0022: Downloads/Quarantine Retention

## Status

Accepted

## Context

Diagnosis of `app/services/quarantine.py`, `app/api/admin_quarantine.py`, `app/services/downloads.py`, and `app/core/release_tokens.py` confirmed no deletion path exists anywhere: `release_file()`/`reject_file()` only flip `QuarantineFile.status`, never touch `storage_object_id` or the staged bytes on disk. Every downloaded file — released, quarantined, or rejected — accumulates in the database and in `download_staging_dir` forever. This is both a storage-growth problem and a data-minimization/compliance one: `original_name`, `source_host`, and URLs for files a user already retrieved (or that were rejected long ago) are retained with no expiry.

`app/services/downloads.py`'s `_stage_file()` stores bytes content-addressed by SHA-256 (`storage_object_id` = `{staging_dir}/{sha256}`). This is not necessarily 1:1 with `QuarantineFile` rows: two different users (or the same user twice) downloading identical content produce two rows sharing one file on disk — confirmed by reading `_stage_file()` and the per-session dedup check in `process_new_downloads()`, which only dedupes within a single session, not globally. Any retention deletion must count live references to a hash before removing its bytes.

`QuarantineStatus` already has a `DELETED` value (`app/models/enums.py`), already wired into `app/api/files.py`'s "deleted" filter group for the user's own file history and already documented as a terminal state in `docs/quarantine.md`'s state machine (`... → (RELEASED | REJECTED | DELETED)`) — but nothing had ever set it. This is clearly the intended target state for exactly this kind of automatic expiry, not a new concept.

`QuarantineFile` has only `CreatedAtMixin` (`created_at`), no `updated_at`. `reviewed_at` is set by the manual `release_file()`/`reject_file()` path but **not** by `scan_and_finalize()`'s auto-release/auto-reject path (`app/services/scanning.py`) — that path sets `status` directly with no separate review timestamp, since it happens synchronously within the same call as row creation.

## Decision

Add `app/core/quarantine_retention.py`, an in-process periodic job (same pattern as `node_poller.py`/`download_poller.py`/`orphan_reconciler.py`), started/stopped from `app/main.py`'s lifespan alongside `node_poller`, gated by the same `listener_mode in ("admin", "both")` condition.

Each cycle (`OPENRBI_QUARANTINE_RETENTION_INTERVAL_SECONDS`, default 3600s):

1. **Two configurable windows**, applied against an *effective status timestamp* — `reviewed_at` when set, else `created_at` (covers both the manual-review and auto-finalize paths correctly):
   - `RELEASED` files: `OPENRBI_QUARANTINE_RETENTION_RELEASED_HOURS`, default **24h**. Short — a `RELEASED` file is cheap to re-request (a fresh 5-minute release token via `app/core/release_tokens.py`) and has no forensic value once delivered; 24h comfortably covers a user coming back for a second download.
   - `QUARANTINED`/`REJECTED` files: `OPENRBI_QUARANTINE_RETENTION_QUARANTINED_DAYS`, default **90 days**. Long — these retain incident-review value; grouped together per the task brief's own framing (both are "not yet auto-cleared" outcomes an investigator might still want to look at).
2. **Open-incident exception**: a file referenced by an `Incident` still in `NEW`/`INVESTIGATING` is skipped regardless of age — checked via `Incident.quarantine_file_id` before touching anything. A `RESOLVED`/`FALSE_POSITIVE` incident no longer protects the file.
3. **Hash-safe deletion**: bytes at `storage_object_id` are only removed from disk if no other, still-live (`status != DELETED`) `QuarantineFile` row shares the same `sha256`. If the `os.remove()` itself fails (permissions, already-gone-but-not-`FileNotFoundError`), the row is **not** flipped to `DELETED` — fail closed, retried next cycle, never a DB state claiming deletion that didn't actually happen.
4. **Soft delete, not a hard row delete**: the row transitions to `QuarantineStatus.DELETED` (the existing, previously-unused terminal state) with `storage_object_id` cleared and the compliance-sensitive descriptive fields scrubbed (`original_name` → a fixed placeholder, `source_host`/`initial_url`/`final_url`/`redirect_chain` → `NULL`). `sha256`, `size_bytes`, `detected_mime`, `extension`, and the status/timestamps are kept — they carry no personally-identifying/URL information and are needed for `app/api/files.py`'s existing "deleted" filter group and dashboard file-status statistics to keep working.
5. Every deletion is audited: a new `SecurityEventType.QUARANTINE_FILE_RETENTION_EXPIRED` event, with `original_name`/`sha256`/`previous_status` in metadata **before** scrubbing — so "where did my file go" is always answerable from the audit log even after the row itself has been scrubbed.

## Alternatives Considered

- **Hard-delete the `QuarantineFile` row** — rejected: breaks `app/api/files.py`'s "deleted" history view and dashboard file-status counts (`app/services/dashboard.py`'s `file_statuses_24h`), and removes the anchor the `QUARANTINE_FILE_RETENTION_EXPIRED` audit event's `quarantine_file_id` FK points to.
- **Keep `original_name`/`source_host` on the row indefinitely, only delete bytes** — rejected: the task's own stated compliance concern is specifically about unbounded retention of this descriptive metadata, not just the file content.
- **One single retention window for everything** — rejected per the task brief's explicit split: a `RELEASED` file's forensic value is materially lower than a `QUARANTINED`/`REJECTED` one's, and collapsing them either over-retains delivered files or under-retains incident-relevant ones.
- **Use `created_at` alone for every status** — rejected: for a file that sat `QUARANTINED` for weeks before a manual admin review, `created_at` would understate how long it's actually been in its terminal state; `reviewed_at` (when present) is the correct anchor.

## Consequences

- Storage and row growth in `download_staging_dir`/`quarantine_files` is now bounded instead of unbounded.
- Descriptive metadata for old, already-resolved files is scrubbed automatically, closing the data-minimization gap the task brief called out.
- Every automatic deletion is audited (`QUARANTINE_FILE_RETENTION_EXPIRED`), so "why is this file gone" is always answerable.
- A file tied to an open `Incident` is never auto-deleted out from under an active investigation.
- Same split-deployment caveat as `docs/adr/0021`: a `user`-only process does not run this job, matching `node_poller`'s existing behavior.
- No manual "clean up now" admin action in this change — out of scope per the task brief; a small follow-up if wanted later.
