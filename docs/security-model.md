# Security Model

## Sandbox model

Each browser session runs in its own container (see [ADR 0010](adr/0010-docker-sandbox-provider.md)), created and destroyed exclusively by the Session Agent (see [ADR 0004](adr/0004-separate-session-agent.md)). Hardening baseline (all enforced at the container-runtime level, not just documented intent):

- non-root user inside the container
- `no-new-privileges`
- Linux capabilities dropped as fully as the browser allows
- read-only root filesystem where practical, with an explicit, size-limited tmpfs/volume for the browser profile
- no host network, no privileged mode, no Docker socket mount
- PID limit, RAM limit, CPU limit, temporary storage limit (defaults: 2 CPUs, 2 GB RAM, PID limit 512, 2 GB temp storage — all configurable, see [ADR 0010](adr/0010-docker-sandbox-provider.md) and §24 of the project brief)
- seccomp/AppArmor profiles appropriate to a browser workload
- a dedicated temporary browser-profile path, destroyed at session end (see [ADR 0007](adr/0007-no-persistent-browser-profiles.md))

## Known interim gaps (tracked, not silent)

Phases 6–8 built real sandbox lifecycle and remote-display mechanics ahead of Phase 9's network isolation. Until Phase 9 lands:

- Browser sandboxes join the same docker network as the control plane (backend, Postgres, Redis) rather than an isolated network — there is currently no egress filtering at all for a running sandbox, and no barrier between it and the control-plane network segment. This is not a regression introduced by Phase 8; no egress restriction existed before it either. Phase 9 replaces this with a dedicated, egress-filtered browser-plane network plus a narrow, display-only path back to the control plane.
- The VNC server inside each sandbox (x11vnc) runs without its own password (`-nopw`), relying entirely on network-level access control (only the backend's display relay can reach it) rather than VNC authentication. Once Phase 9's segmentation exists, this remains an intentional choice — the actual authorization boundary is the backend's session-ownership check on `/display/{id}/ws` (itself still pending full enforcement until Phase 10/11's BrowserSession model exists), not VNC's own weak auth.

## Network isolation

Browser sandboxes may reach the public internet only. Blocked by default, at minimum:

- IPv4: `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`, `192.0.0.0/24`, `192.168.0.0/16`, `198.18.0.0/15`, `224.0.0.0/4`, `240.0.0.0/4`
- IPv6: `::1/128`, `fc00::/7`, `fe80::/10`, `ff00::/8`
- Dynamically: Docker networks, host networks, control-plane networks, cloud metadata endpoints, management networks

DNS resolution for sandboxed sessions goes through a controlled resolver/proxy (planned, Phase 9) so that DNS answers pointing at a blocked address are rejected rather than allowed to connect — this specifically defeats DNS-rebinding attacks. Any connection attempt or resolution that would land on a blocked address is denied and generates a `NETWORK_ACCESS_BLOCKED` security event.

## File transfer

Downloads and uploads are fail-closed pipelines (see [ADR 0008](adr/0008-fail-closed.md) and [quarantine.md](quarantine.md)):

- No download reaches the local client unscanned or unvetted by policy.
- No local directory is ever mounted directly into a browser sandbox for uploads; uploads go through a dedicated gateway (hash → type detection → scan → policy → temporary in-sandbox availability).
- File decisions consider more than extension or declared Content-Type: user, groups, source, declared MIME, detected/magic-byte MIME, extension, size, scanner result, and the policy version used — recorded per-decision.

## Fail-closed rules

See [ADR 0008](adr/0008-fail-closed.md) for the authoritative statement. Summary: scanner down → no auto-release; policy engine error → no release; undetectable file type → quarantine; quarantine storage down → downloads blocked entirely. These rules apply uniformly to both the download and upload pipelines.

## MFA

TOTP is mandatory for ADMIN and SECURITY_REVIEWER roles (see [ADR 0002](adr/0002-totp-mfa.md)). TOTP secrets are encrypted at rest at the application layer. Recovery codes are shown once, stored only as hashes, and invalidated individually on use. An admin-triggered MFA reset always creates a `MFA_RESET` security event.

## Session isolation

No two users' sessions ever share a browser instance, a writable profile, or a filesystem mount. Admins/Security Reviewers can Disconnect (drop the remote-display connection, sandbox persists), Isolate (network egress deny-all, clipboard deny both directions, uploads/downloads/new file-shares deny-all, sandbox persists for investigation), or Kill (idempotent full destruction) a session — see [session-lifecycle.md](session-lifecycle.md).

## Secrets

No secrets in git. No hardcoded passwords or tokens. Database credentials, session-signing keys, and the TOTP secret-encryption key are provided via environment variables / a secrets manager at deploy time (see [deployment.md](deployment.md) and `.env.example`). The Session Agent's internal API credentials are provisioned the same way and are never accessible from inside a browser sandbox.

## Audit

Security Events are append-only and not deletable through the normal admin UI (see [docs/architecture.md](architecture.md) for the event flow, and the master event list in the project's Security Event model). Logs never contain passwords, MFA secrets, complete tokens, or file contents.

## Data protection / retention

Persisted: users, roles, groups, MFA metadata, policies and policy versions, incidents, security events, audit metadata, quarantine metadata, system configuration. Never persisted beyond session lifetime: browser cache, cookies, browser history, saved browser passwords, temporary profiles, session `/tmp` contents (see [ADR 0007](adr/0007-no-persistent-browser-profiles.md)).
