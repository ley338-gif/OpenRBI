# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Supported |
| < 1.0 | Not supported |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for suspected security vulnerabilities. Instead, report privately to the maintainers (see repository contact details) with:

- A description of the issue and its potential impact
- Steps to reproduce, or a proof of concept
- The commit/version you tested against

We will acknowledge reports and work with you on a fix and coordinated disclosure timeline. Please do not include exploit details or proof-of-concept payloads in public issues, discussions, or pull requests.

## Security assumptions

OpenRBI's isolation model assumes:

- The underlying Docker/container runtime and host kernel are trusted and patched.
- Administrators and infrastructure operators are trusted; OpenRBI does not defend against a malicious admin or a compromised control-plane host.
- The reverse proxy terminates TLS with a validly configured certificate.
- Secrets (database credentials, session signing keys, TOTP encryption keys) are provisioned outside of git via environment variables or a secrets manager, never committed.

See [docs/threat-model.md](docs/threat-model.md) for the full attacker-model breakdown.

## Known MVP limitations

MVP 1 does not defend against: host kernel compromise, hypervisor escape, sophisticated zero-days against the sandbox runtime, or a malicious infrastructure administrator. It also does not yet implement SSO/enterprise identity federation, full DLP/content disarm & reconstruction, or high availability. See [docs/threat-model.md](docs/threat-model.md) for the complete non-goals list.
