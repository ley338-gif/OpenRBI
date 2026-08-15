# OpenRBI

**OpenRBI** is a self-hosted, open-source Remote Browser Isolation (RBI) platform for organizations. It runs web browsing sessions server-side, in isolated sandboxes, and streams the display to the user — so the endpoint never executes untrusted web content, and the organization's internal networks stay unreachable from the browsing session.

## Project status

**Pre-alpha / MVP 1 in progress.** OpenRBI is not yet feature-complete and has not undergone independent security review. Do not deploy it in a production or security-critical environment yet. See [docs/threat-model.md](docs/threat-model.md) for what is and isn't covered today, and [CHANGELOG.md](CHANGELOG.md) for progress.

The MVP 1 build order and scope are tracked internally against the phases in [docs/development.md](docs/development.md).

## MVP 1 goals

- Admins manage users, groups, roles, MFA, policies, sessions, incidents, and quarantine.
- Users log in locally with username/password + TOTP MFA.
- Users launch a server-side remote browser (Firefox) from the web portal, viewed via noVNC.
- Each browser session is isolated from every other user's session.
- Browser sessions can reach the public internet but not internal networks, the host, or the OpenRBI control plane.
- File transfers (download/upload) are controlled by versioned policies, malware scanning, and quarantine.
- Admins/Security Reviewers can disconnect, isolate, or kill sessions on demand.
- Every security-relevant action is captured in an append-only audit log.

## Quick start

> See [docs/deployment.md](docs/deployment.md) for a full production deployment (TLS, firewall, backup/restore). The quick start below is local/evaluation only.
> The deliberately narrow OpenRBI 1.0 platform and version scope is defined in [docs/supported-configurations.md](docs/supported-configurations.md). Segmented Deployment and gVisor are technology previews, not supported v1 production paths.

```bash
git clone <this-repo>
cd OpenRBI
cp .env.example .env   # fill in secrets before first run
docker compose up -d --build
```

Then open the **Admin Portal** at `http://localhost:8080/admin/` — a fresh install has no accounts yet, so it shows **Initial System Setup** instead of a login form. Retrieve the one-time setup token with `docker compose logs backend | grep -A3 "initial setup token"`, create the first administrator, and complete TOTP enrollment; no manual database access is ever required (see [docs/deployment.md#first-run-setup-roadmap-b19](docs/deployment.md#first-run-setup-roadmap-b19)). After that, the **User Portal** is at `http://localhost:8080/`. Both are real, API-backed UIs — see [docs/user-guide.md](docs/user-guide.md) and [docs/admin-guide.md](docs/admin-guide.md). Admin/Security Reviewer accounts are walked through mandatory TOTP enrollment on first login.

## Architecture overview

OpenRBI separates a **control plane** (backend API, database, policy engine) from a **browser plane** (per-user sandboxed browser containers, reachable only via a dedicated, minimally privileged **Session Agent** — the web backend never touches the Docker socket directly). Sandbox, display, browser, and file-scanner integrations sit behind provider interfaces (`SandboxProvider`, `DisplayProvider`, `BrowserProvider`, `FileScanner`) so MVP 1's concrete choices (Docker, noVNC, Firefox, ClamAV) can be swapped or extended (gVisor, KasmVNC, Chromium, ...) without touching core logic.

Two separate frontends — a **User Portal** and an **Admin Portal** — sit in front of the API (`frontend/user/`, `frontend/admin/`, sharing common code from `frontend/shared/`), each talking only to the listener mode it's meant for. The backend itself can run as a `user`- or `admin`-only listener (`OPENRBI_LISTENER_MODE`, default `both`); in `user` mode, admin routes don't exist in that process at all (a `404`, not a `403`). This is preparation for a future Segmented deployment with genuinely separate portal origins, not yet the default — see [docs/architecture.md](docs/architecture.md) for the full component and trust-boundary breakdown, and [docs/deployment.md](docs/deployment.md#compact-vs-segmented-productization-v011) for Compact vs. Segmented.

## Security

OpenRBI is designed fail-closed: if the malware scanner, policy engine, or quarantine storage is unavailable, file transfers are blocked rather than silently allowed. No security decision is made only in the frontend. See:

- [docs/security-model.md](docs/security-model.md) — sandbox model, network isolation, fail-closed rules, MFA, secrets, audit
- [docs/threat-model.md](docs/threat-model.md) — assets, trust boundaries, attacker models, explicit non-goals
- [docs/security-self-assessment.md](docs/security-self-assessment.md) — a structured first-party check of every claimed control against the actual code, with file/line evidence and open gaps stated explicitly. **Not** a substitute for the independent external review still pending before any production use.
- [SECURITY.md](SECURITY.md) — supported versions and how to report a vulnerability

**OpenRBI never claims a file is "safe."** Status wording is deliberately limited to things it can actually verify: *No threat detected*, *Scan completed*, *Policy allowed*, *Quarantined*.

## Documentation

| Doc | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, data flows, trust boundaries, provider architecture |
| [docs/threat-model.md](docs/threat-model.md) | Threat model and non-goals |
| [docs/security-model.md](docs/security-model.md) | Sandbox, network, file-transfer, MFA, secrets, audit rules |
| [docs/security-self-assessment.md](docs/security-self-assessment.md) | Every claimed control checked against the actual code, with evidence and open gaps |
| [docs/policies.md](docs/policies.md) | Roles vs. groups, policy model, MIME/source matching |
| [docs/session-lifecycle.md](docs/session-lifecycle.md) | Session states and transitions |
| [docs/quarantine.md](docs/quarantine.md) | Download pipeline, scanning, quarantine, release/reject |
| [docs/admin-guide.md](docs/admin-guide.md) | Admin operations |
| [docs/user-guide.md](docs/user-guide.md) | End-user operations |
| [docs/deployment.md](docs/deployment.md) | Installation, HTTPS, secrets, backup |
| [docs/supported-configurations.md](docs/supported-configurations.md) | Authoritative supported, experimental, and unsupported v1 configurations |
| [docs/release/publishing.md](docs/release/publishing.md) | Guarded release dry-run, image publication, and provenance procedure |
| [docs/release/sbom.md](docs/release/sbom.md) | CycloneDX SBOM generation, release assets, and limitations |
| [docs/release/fresh-install-acceptance.md](docs/release/fresh-install-acceptance.md) | Executable clean-install protocol and step-by-step acceptance criteria |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems |
| [docs/development.md](docs/development.md) | Dev environment, repo structure, build phases |
| [docs/api.md](docs/api.md) | API reference |
| [docs/adr/](docs/adr/) | Architecture Decision Records |

## Scope

MVP 1 deliberately excludes OIDC/SAML/WebAuthn federation, Kubernetes, real multi-node scheduling, HA, SIEM integration, threat intel feeds, full DLP, content disarm & reconstruction, persistent browser profiles, SSL inspection, and ML-based detection. The architecture avoids blocking these as future work without half-building them now.

LDAP/LDAPS authentication against an existing Active Directory (Roadmap Phase B / B1) is implemented as an equal, parallel option alongside local login, fully configurable through the Admin Portal — no `.env` editing or backend restart needed (Roadmap B1.8, [ADR 0016](docs/adr/0016-ldap-admin-configuration.md)) — see [docs/admin-guide.md](docs/admin-guide.md#ldapldaps-authentication-roadmap-phase-b--b1) for configuration and [ADR 0015](docs/adr/0015-auth-provider-abstraction.md) for the underlying design.

## License

[GNU AGPLv3](LICENSE). Chosen to keep this an open-core project — if you run a modified version of OpenRBI as a network service (including a hosted/managed offering), the AGPL's core obligation is that your users get access to your modified source, closing the loophole plain GPL leaves for SaaS-style use without ever distributing the binary.
