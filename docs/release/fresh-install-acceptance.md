# Fresh-install acceptance protocol

`scripts/run-fresh-install-acceptance.sh` is the executable v1 clean-install
protocol and a required release gate. It must run on a clean x86_64 Linux host
with Docker Engine, Compose, `iptables`, `curl`, `openssl`, and passwordless or
interactive `sudo`. It refuses to overwrite an existing `.env`.

The runner uses the dedicated `openrbi-acceptance` Compose project and always
removes its containers, volumes, generated `.env`, and tagged firewall rules.
It never reports a step as successful until the associated command or API
assertion has completed.

| Step | Action | Verifiable acceptance criterion |
|---:|---|---|
| 1 | Clean environment | No pre-existing acceptance project or `.env`; dedicated empty volumes are created. |
| 2–3 | Configuration and secrets | A mode-600 `.env` is generated with independent random PostgreSQL, agent, LDAP placeholder, and TOTP-encryption secrets; Compose config validates. |
| 4 | Compose build | Backend, Session Agent, and frontend images build from the checked-out source and locked dependencies. |
| 5 | Start | PostgreSQL, Valkey, ClamAV, then the complete Compact stack start; proxy serves user/admin portals and health. |
| 6 | Migration | `alembic upgrade head` succeeds against the empty PostgreSQL volume. |
| 7 | Browser image | The actual hardened `openrbi-browser:latest` image builds. |
| 8 | Network isolation | Host `DOCKER-USER` rules are applied for the acceptance browser network and their marker is observable. |
| 9 | Initial admin | `/setup/status` is true and the console-only token creates the first ADMIN without database access. |
| 10 | MFA enrollment | A real TOTP secret is enrolled and confirmed; recovery codes are returned and setup closes. |
| 11 | Admin login | The setup session is discarded; a fresh password login plus a new live TOTP succeeds and `/auth/me` proves ADMIN. |
| 12 | User creation | The authenticated ADMIN creates a local USER through `POST /admin/users`. |
| 13 | User login | The new USER authenticates normally and `/auth/me` proves the least-privileged role. |
| 14 | Browser session | `POST /sessions` creates a real sandbox and returns only after its display is reachable and state is `ACTIVE`. |
| 15 | Session end | The user terminates it; API state is `TERMINATED` and no managed sandbox remains. |
| 16 | Health | Liveness is `ok`; every aggregate dependency, including ClamAV, runtime, browser image, and storage, is `HEALTHY`. |

Run from a clean clone:

```sh
./scripts/run-fresh-install-acceptance.sh
```

The workflow uses development-mode cookies because it reaches the isolated
local HTTP proxy on the ephemeral CI host. Production deployments must still
use `OPENRBI_ENVIRONMENT=production` and the documented HTTPS reverse proxy.
