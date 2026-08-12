# Policies

> Status: implemented (Phase 12) — `app/services/policy_engine.py` (evaluation), `app/services/policies.py` (admin CRUD/versioning), `app/api/policies.py` (`/admin/policies/*`). Wired into the real download (Phase 13) and upload (Phase 16) pipelines — see [quarantine.md](quarantine.md) — and exercised directly via `evaluate_file_action` and its admin API.

## Roles vs. groups

Roles (`USER`, `SECURITY_REVIEWER`, `ADMIN`) grant **capabilities** in the product (what screens/actions are available). Groups are a separate concept and drive **security policy** (what a session is allowed to do: network, downloads, uploads, clipboard, browser, session limits, MIME/source rules). A user can belong to multiple groups; roles and groups are independent axes.

## Policy model

Policies are versioned. A published `PolicyVersion` is immutable — editing means creating a new draft version. Workflow: create draft → edit → publish → (further edits create a new version) → prior versions remain visible in history → rollback re-activates a prior published version as current. Every policy *decision* (a session's network permission, a file's action) records which `PolicyVersion` produced it.

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

`Policy.policy_type` (`NETWORK`, `DOWNLOADS`, `UPLOADS`, `CLIPBOARD`, `BROWSER`, `SESSION`, `MIME`, `SOURCE`) is a label chosen at creation time — the admin API (`app/api/policies.py`) accepts and stores it, and it's shown back in `PolicySummary`/`PolicyDetail`, but it is **not** read by anything at decision time. `app/services/policy_engine.py`'s `evaluate_file_action` — the only runtime consumer of policy content in MVP 1 — queries `FilePolicyRule` rows (which only ever have `rule_type` `MIME` or `SOURCE`) reachable through a user's groups, entirely independent of what `policy_type` the parent `Policy` was labeled with. A `Policy` created with `policy_type=NETWORK` that happens to have `MIME` file rules attached to its published version is evaluated exactly the same as one labeled `MIME`; a `Policy` labeled `CLIPBOARD`/`BROWSER`/`SESSION`/`NETWORK` with no file rules attached has **zero runtime effect**, however its freeform `content` JSONB is filled in.

Concretely, per the categories the project brief names:

- **Downloads/uploads (MIME/SOURCE rules)**: fully implemented and enforced — see [quarantine.md](quarantine.md). Final action is one of `AUTO_RELEASE`, `QUARANTINE`, `DENY`.
- **Network**: egress control is real and enforced, but as a single static blocklist applied to the whole `browser-plane` network (`scripts/setup-network-isolation.sh`, see [security-model.md](security-model.md#network-isolation)) — not per-group/per-policy. A `Policy` labeled `NETWORK` can be created and versioned through the admin API but has no effect; there is no per-group network policy enforcement in MVP 1.
- **Clipboard**: **not implemented as a policy.** During a normal `ACTIVE` session there is no group-level clipboard control at all (`NONE`/`LOCAL_TO_REMOTE`/`REMOTE_TO_LOCAL`/`BIDIRECTIONAL_TEXT` are documented as intended values but nothing reads or enforces them). The "clipboard denied" effect of an admin Isolate (see [session-lifecycle.md](session-lifecycle.md)) isn't a separate clipboard-specific control either — `isolate_session` (`app/services/sessions.py`) only ever calls the Session Agent's network-disconnect primitive; clipboard (and everything else that rides over the VNC connection) stops working purely as a side effect of the sandbox losing all network connectivity, the same blunt instrument as the file-transfer denial.
- **Browser / Session**: also not implemented as enforced policy content — browser hardening is a fixed property of the sandbox image (docker/browser/), and session resource limits (`max_sessions_per_user`, CPU/RAM/PID/disk) come from `.env`/request defaults, not from a versioned `Policy`.

This is a real, tracked gap, not a silent one: the data model and admin CRUD support all eight policy types uniformly (by design, so adding real enforcement for one later doesn't need a schema change), but MVP 1 only ever built the *enforcement* for MIME/SOURCE file rules. Creating a `NETWORK`/`CLIPBOARD`/`BROWSER`/`SESSION`-typed policy through the admin API today does not do anything beyond storing it.

## Example

A user in groups `finance` (DENY `.exe`) and `general` (AUTO_RELEASE all Office documents) downloads a `.exe` disguised with a `.docx` extension. Detected/magic-byte MIME shows an executable regardless of extension → `finance`'s `DENY` applies under the conflict model above, regardless of `general`'s more permissive rule.
