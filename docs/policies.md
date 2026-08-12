# Policies

> Status: design reference for Phase 12 (Policy Engine). Not yet implemented — see [development.md](development.md).

## Roles vs. groups

Roles (`USER`, `SECURITY_REVIEWER`, `ADMIN`) grant **capabilities** in the product (what screens/actions are available). Groups are a separate concept and drive **security policy** (what a session is allowed to do: network, downloads, uploads, clipboard, browser, session limits, MIME/source rules). A user can belong to multiple groups; roles and groups are independent axes.

## Policy model

Policies are versioned. A published `PolicyVersion` is immutable — editing means creating a new draft version. Workflow: create draft → edit → publish → (further edits create a new version) → prior versions remain visible in history → rollback re-activates a prior published version as current. Every policy *decision* (a session's network permission, a file's action) records which `PolicyVersion` produced it.

## Conflict model (deterministic)

When multiple applicable group policies disagree on a file rule, the outcome is decided by this fixed precedence — never by group ordering:

1. `DENY` wins over everything.
2. Otherwise `QUARANTINE` wins.
3. Otherwise `AUTO_RELEASE` / `SCAN_AND_ALLOW` wins.
4. Otherwise the default policy applies.

This ordering is deliberately conservative: any single group requiring denial or quarantine overrides a more permissive group the same user also belongs to.

## MIME and source matching

A file decision is never based on extension or HTTP `Content-Type` alone. Inputs considered: user, groups, source, declared MIME type, detected MIME type (magic bytes / actual file type), extension, file size, scanner result, and the policy version in force.

Source rules are normalized, not string-contains matched. A rule like `*.microsoft.com` must match `download.microsoft.com` and `office.microsoft.com`, but must **not** match `microsoft.com.attacker.org` or `evil-microsoft.com`. Matching is done against a parsed hostname's registrable-domain/subdomain structure, not substring search. Stored per download/upload: `initial_url`, `final_url`, `source_hostname`, `redirect_chain`, and whether TLS was used.

## Download / upload / clipboard rules

- **Downloads**: see [quarantine.md](quarantine.md) for the full pipeline; final action is one of `AUTO_RELEASE`, `QUARANTINE`, `DENY`.
- **Uploads**: policy can allow/block globally or per MIME type/group; no local directory is ever mounted directly into a sandbox.
- **Clipboard**: text-only in MVP 1. Policy values: `NONE`, `LOCAL_TO_REMOTE`, `REMOTE_TO_LOCAL`, `BIDIRECTIONAL_TEXT`. No file clipboard in MVP 1.

## Example

A user in groups `finance` (DENY `.exe`) and `general` (AUTO_RELEASE all Office documents) downloads a `.exe` disguised with a `.docx` extension. Detected/magic-byte MIME shows an executable regardless of extension → `finance`'s `DENY` applies under the conflict model above, regardless of `general`'s more permissive rule.
