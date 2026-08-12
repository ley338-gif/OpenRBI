# Threat Model

## Assets

- User credentials (password hashes, TOTP secrets, recovery codes)
- Session tokens / server-side session state
- Internal networks and hosts reachable from the OpenRBI server
- Downloaded/uploaded files in transit and in quarantine
- Audit/security event log integrity
- Policy definitions and their version history
- The Session Agent's runtime credentials (Docker socket / equivalent)

## Trust boundaries

See [architecture.md](architecture.md#trust-boundaries) for the diagram. The three boundaries that matter most:

1. **End-user browser ↔ Reverse Proxy** — untrusted client, TLS-terminated.
2. **Control Plane ↔ Session Agent** — the only path by which the control plane can affect sandbox runtime state; authenticated, internal-only.
3. **Browser Sandbox ↔ everything else** — a sandbox must never reach PostgreSQL, Redis, the Docker socket, the admin API, quarantine storage, or other users' sandboxes. Its only permitted egress is the public internet.

## Attacker models considered

| Attacker | Capability assumed | Primary mitigations |
|---|---|---|
| Malicious website | Fully hostile page content, arbitrary JS, exploit attempts against the browser | Isolation runs the browser server-side; only rendered pixels reach the user. Network egress limited to public internet (see below). |
| Compromised browser (renderer exploited) | Code execution inside the Firefox process | Container hardening (non-root, dropped caps, read-only rootfs, seccomp/AppArmor, PID/CPU/RAM limits, no host network, no privileged mode, no Docker socket) limits blast radius to the sandbox container. |
| Compromised browser container | Full control of the sandbox container's OS-level view | Network isolation (RFC1918/link-local/metadata/Docker/host/control-plane ranges blocked, DNS-rebinding protection) prevents lateral movement. No mounts between sessions. Sandbox has no path to Session Agent's privileged credentials. |
| Malicious normal user | Valid low-privilege account, uses OpenRBI as intended but tries to escalate or access others' data | Central authorization (role/group checks server-side), UUID-based resource references, per-user session/data isolation, audit logging of all actions. |
| Compromised normal user account | Attacker has valid credentials (phished, reused password) | MFA required for privileged roles; session isolation still prevents cross-user access even with valid low-privilege credentials; admin can disconnect/isolate/kill sessions and disable accounts. |
| Stolen passwords | Attacker has a password but not the second factor | TOTP MFA blocks login for MFA-enrolled accounts; failed attempts generate `USER_LOGIN_FAILED`/`MFA_FAILED` events for detection. |
| Malicious file | A file downloaded/uploaded through a session is malware or a policy-violating type | Fail-closed download/upload pipeline: hash, MIME detection (declared + actual/magic-byte), scan, versioned policy decision, quarantine by default for anything not explicitly auto-released. |
| Compromised OpenRBI web application | Attacker achieves code execution or SQL injection in the backend | Backend has no Docker socket access (see [ADR 0005](adr/0005-no-docker-socket-in-backend.md)), so this does not directly yield host/container-runtime compromise. Least-privilege service accounts, parameterized queries, append-only audit log limit further damage and preserve forensic trail. |

## Explicit non-goals (residual risk MVP 1 does not fully address)

OpenRBI does **not** claim to fully defend against:

- **Host kernel compromise** — if the underlying Linux kernel itself is exploited (e.g. via a container-escape zero-day), all containers on that host are at risk. Mitigated but not eliminated by seccomp/AppArmor and the optional gVisor runtime.
- **Hypervisor escape** — out of scope; OpenRBI does not mandate a specific virtualization layer for MVP 1.
- **Sophisticated zero-days against the sandbox runtime** — Docker/runc/gVisor vulnerabilities are a residual risk; patch cadence and optional stronger isolation (gVisor, later Kata) reduce but do not eliminate this.
- **A malicious infrastructure administrator** — anyone with host root, database admin, or Session Agent credentials can bypass application-level controls. OpenRBI protects against attackers operating *through* the platform, not against a trusted operator abusing direct infrastructure access.

OpenRBI never claims a scanned file is "safe" — status wording is limited to what was actually verified (*No threat detected*, *Scan completed*, *Policy allowed*, *Quarantined*), never a safety guarantee.

## Out of scope for MVP 1 (see README "Scope")

LDAP/AD/Entra ID/OIDC/SAML/WebAuthn federation, Kubernetes orchestration, real multi-node scheduling, HA, SIEM integration, threat intel feeds, full DLP, content disarm & reconstruction, persistent browser profiles, SSL inspection, ML-based detection.
