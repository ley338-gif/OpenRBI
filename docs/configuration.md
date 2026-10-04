# Configuration reference

Every setting OpenRBI reads, in one place. Settings go into `.env` in the checkout (copy `.env.example`); Compose passes the whole file to the backend and the Session Agent (`env_file: .env`), so a variable listed here takes effect after `./scripts/deploy.sh` or `docker compose up -d` recreates the container.

`scripts/check-config-docs.py` (CI) keeps this page in sync with the code: every backend and Session Agent setting has to be listed with its real default, and every variable `.env.example` or the Compose files use has to appear here.

**Default** is the value used when the variable isn't set. *(empty)* means an empty string; for secrets that means "not configured", and the services refuse to start where noted.

## Deployment (`.env`, read by Compose and the scripts)

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | — (required) | Database owner role the `postgres` container creates. `scripts/backup.sh`, `restore.sh` and `deployment.md`'s commands assume `openrbi`. |
| `POSTGRES_PASSWORD` | — (required) | Password of that role. Must match the one in `OPENRBI_DATABASE_URL`. |
| `POSTGRES_DB` | — (required) | Database name. The backup and restore scripts assume `openrbi`. |
| `COMPOSE_FILE` | `docker-compose.yml` | Compose files to combine (unset: `docker-compose.yml`, plus `docker-compose.override.yml` if it exists), e.g. `docker-compose.yml:docker-compose.prod.yml` for the TLS overlay. Read by Compose and `deploy.sh`. |
| `OPENRBI_DOCKER_SOCKET_GID` | — (required) | Group ID of `/var/run/docker.sock` on the host (`stat -c '%g' /var/run/docker.sock`), so the Session Agent can use the socket without running as root. `deploy.sh` fills it in when missing. |
| `OPENRBI_BROWSER_PLANE_SUBNET` | `172.30.0.0/24` | Subnet of the `browser-plane` network the sandboxes run in. |
| `OPENRBI_AGENT_BROWSER_PLANE_IP` | `172.30.0.2` | Fixed address of the Session Agent on `browser-plane`. `scripts/setup-network-isolation.sh` exempts exactly this address (it must belong to the agent), so keep it inside `OPENRBI_BROWSER_PLANE_SUBNET`. |
| `OPENRBI_DB_USER_ROLE_PASSWORD` | *(empty)* | Segmented deployments only: password `scripts/provision-segmented-db-roles.sh` sets for the scoped `openrbi_user` role ([ADR 0025](adr/0025-segmented-credential-scoping.md)). |
| `OPENRBI_DB_ADMIN_ROLE_PASSWORD` | *(empty)* | Same, for the scoped `openrbi_admin` role. |

## Backend (`OPENRBI_*`)

### Core and secrets

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_ENVIRONMENT` | `development` | Anything other than `development` marks the session and CSRF cookies `Secure` (HTTPS only). Set `production` together with the TLS overlay; `deploy.sh` refuses the overlay otherwise. |
| `OPENRBI_LISTENER_MODE` | `both` | Which API surface this process serves: `both`, `user` or `admin` ([ADR 0011](adr/0011-user-admin-listener-separation.md)). Any other value stops the backend at startup. |
| `OPENRBI_TOTP_SECRET_ENCRYPTION_KEY` | *(empty)* | Required. 64 hex characters (`openssl rand -hex 32`) encrypting TOTP secrets and the stored LDAP bind password. Empty or the `.env.example` placeholder stops the backend. Rotate with `scripts/rotate-totp-key.sh`. |
| `OPENRBI_CSRF_SECRET_KEY` | *(empty)* | Required. Signs the CSRF double-submit cookie. Empty or the placeholder stops the backend. |
| `OPENRBI_SESSION_COOKIE_NAME` | `openrbi_session` | Name of the login session cookie. |
| `OPENRBI_SESSION_TTL_SECONDS` | `28800` | Lifetime of a login session (8 hours), also the CSRF cookie's lifetime. |
| `OPENRBI_SETUP_TOKEN_TTL_SECONDS` | `1800` | How long the first-run setup token from the backend log stays valid ([ADR 0017](adr/0017-first-run-bootstrap.md)). |

### Database and Redis

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_DATABASE_URL` | `postgresql+asyncpg://openrbi:openrbi@postgres:5432/openrbi` | PostgreSQL connection (asyncpg driver). Put the real `POSTGRES_PASSWORD` in it. |
| `OPENRBI_DATABASE_URL_USER` | *(empty)* | Segmented only: connection as the scoped `openrbi_user` role, used when `OPENRBI_LISTENER_MODE=user`. Can't be combined with LDAP on a `user` listener (the backend refuses to start). |
| `OPENRBI_DATABASE_URL_ADMIN` | *(empty)* | Segmented only: connection as `openrbi_admin`, used when `OPENRBI_LISTENER_MODE=admin`. |
| `OPENRBI_REDIS_URL` | `redis://redis:6379/0` | Valkey/Redis connection (login sessions, MFA and download tokens, rate limits). |

### Session Agent connection

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_SESSION_AGENT_BASE_URL` | `http://session-agent:8100` | Where the backend reaches the default node's Session Agent. |
| `OPENRBI_SESSION_AGENT_API_TOKEN` | *(empty)* | Required. Shared token for the default node; must equal the agent's `OPENRBI_AGENT_API_TOKEN`. Empty or the placeholder stops the backend. |
| `OPENRBI_SESSION_AGENT_API_TOKEN_USER` | *(empty)* | Segmented only: `user`-scope token, used by a `user` listener instead of the shared one (equals the agent's `OPENRBI_AGENT_API_TOKEN_USER`). The shared token is still required. |
| `OPENRBI_SESSION_AGENT_API_TOKEN_ADMIN` | *(empty)* | Segmented only: `admin`-scope token for an `admin` listener. |

### Sessions

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_MAX_SESSIONS_PER_USER` | `1` | Live sessions a user may have at once. `ISOLATING`/`ISOLATED` sessions don't count ([session-lifecycle.md](session-lifecycle.md#transitions)). |
| `OPENRBI_SESSION_DISCONNECTED_TIMEOUT_SECONDS` | `3600` | A session nobody is viewing for this long is terminated (`SESSION_TIMED_OUT`): `DISCONNECTED`, or `ACTIVE` without a viewer since it started or was restored. `0` disables it. |
| `OPENRBI_SESSION_STUCK_TRANSITION_TIMEOUT_SECONDS` | `600` | A session stuck in `STARTING` or `TERMINATING` this long is torn down again. `0` disables it. |
| `OPENRBI_SESSION_REAPER_INTERVAL_SECONDS` | `60` | How often the two timeouts above are checked. |
| `OPENRBI_ORPHAN_RECONCILE_INTERVAL_SECONDS` | `300` | How often sandbox containers without a live session are looked for ([ADR 0021](adr/0021-orphan-container-reconciliation.md)). |
| `OPENRBI_ORPHAN_RECONCILE_GRACE_CYCLES` | `2` | Consecutive checks a container must look orphaned before it is removed. |

### Downloads, scanning and retention

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_DOWNLOAD_STAGING_DIR` | `/app/data/staging` | Quarantine storage directory inside the backend container (the `quarantine-staging` volume). |
| `OPENRBI_DOWNLOAD_POLL_INTERVAL_SECONDS` | `3.0` | How often running sandboxes are checked for new downloads. |
| `OPENRBI_DOWNLOAD_MAX_SIZE_BYTES` | `524288000` | Downloads larger than this (500 MiB) are never fetched; they stay `QUARANTINED` with a scan error ([quarantine.md](quarantine.md#download-pipeline)). |
| `OPENRBI_CLAMAV_HOST` | `clamav` | ClamAV daemon host. |
| `OPENRBI_CLAMAV_PORT` | `3310` | ClamAV daemon port. |
| `OPENRBI_QUARANTINE_RETENTION_RELEASED_HOURS` | `24.0` | `RELEASED` files are deleted this long after release ([quarantine.md](quarantine.md#retention)). |
| `OPENRBI_QUARANTINE_RETENTION_QUARANTINED_DAYS` | `90.0` | `QUARANTINED`/`REJECTED` files are deleted after this many days, unless an open incident references them. |
| `OPENRBI_QUARANTINE_RETENTION_INTERVAL_SECONDS` | `3600.0` | How often the retention job runs. |

### Workers and metrics

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_NODE_POLL_INTERVAL_SECONDS` | `15.0` | How often every approved node's telemetry is polled. |
| `OPENRBI_NODE_HEARTBEAT_STALE_SECONDS` | `45.0` | A node not heard from for this long is `OFFLINE`. |
| `OPENRBI_NODE_CPU_DEGRADED_PERCENT` | `90.0` | CPU load at which a node counts as `DEGRADED`. |
| `OPENRBI_NODE_RAM_DEGRADED_PERCENT` | `90.0` | RAM use at which a node counts as `DEGRADED`. |
| `OPENRBI_CAPACITY_BOUND_WARNING_MINUTES` | `10` | A node whose capacity is limited by RAM or CPU for this long raises a dashboard warning. |
| `OPENRBI_METRICS_RETENTION_DAYS` | `7` | Worker metric samples older than this are pruned. |

### LDAP

Only consulted until a configuration is saved in the Admin Portal (**Administration → LDAP / identity**); see [admin-guide.md](admin-guide.md#ldapldaps-authentication-roadmap-phase-b--b1). `OPENRBI_LDAP_CA_CERT_FILE` stays in effect either way.

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_LDAP_ENABLED` | `false` | Turns LDAP login on. Then `OPENRBI_LDAP_SERVER_URI`, `_BIND_DN`, `_BIND_PASSWORD` and `_BASE_DN` are required, or the backend doesn't start. |
| `OPENRBI_LDAP_SERVER_URI` | *(empty)* | `ldaps://host:636` or `ldap://host:389` (the latter only with StartTLS). |
| `OPENRBI_LDAP_USE_STARTTLS` | `true` | StartTLS for `ldap://`. Plain `ldap://` without it is refused. |
| `OPENRBI_LDAP_BIND_DN` | *(empty)* | Service account used for the user search. |
| `OPENRBI_LDAP_BIND_PASSWORD` | *(empty)* | Its password. |
| `OPENRBI_LDAP_BASE_DN` | *(empty)* | Search base for user entries. |
| `OPENRBI_LDAP_USER_SEARCH_FILTER` | `(sAMAccountName={username})` | Filter for the user entry; `{username}` is replaced by the escaped login name. |
| `OPENRBI_LDAP_GROUP_ATTRIBUTE` | `memberOf` | Attribute listing the user's group DNs. |
| `OPENRBI_LDAP_GROUP_ROLE_MAPPING` | `{}` | JSON object `{"<group DN>": "ADMIN"}`; values are `USER`, `SECURITY_REVIEWER` or `ADMIN`. No match means `USER`. |
| `OPENRBI_LDAP_CA_CERT_FILE` | *(empty)* | PEM bundle trusted in addition to the system store, path inside the container. Must exist when set. |

### Network isolation health

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_NETWORK_ISOLATION_MARKER_FILE` | `/etc/openrbi/network-isolation/marker` | Marker `setup-network-isolation.sh` writes on the host (mounted read-only); its presence and age drive the `network_isolation` health check. |
| `OPENRBI_NETWORK_ISOLATION_MAX_STALENESS_SECONDS` | `900.0` | A marker older than this turns the check `DEGRADED`. Keep it well above the systemd timer's interval. |

## Session Agent (`OPENRBI_AGENT_*`)

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_AGENT_API_TOKEN` | *(empty)* | Shared full-access token; must equal the backend's `OPENRBI_SESSION_AGENT_API_TOKEN`. Either this or both scoped tokens must be set, or the agent doesn't start. |
| `OPENRBI_AGENT_API_TOKEN_USER` | *(empty)* | Segmented only: token accepted for `user`-scope calls. |
| `OPENRBI_AGENT_API_TOKEN_ADMIN` | *(empty)* | Segmented only: token accepted for every call. |
| `OPENRBI_AGENT_ENVIRONMENT` | `development` | Read but not used by the agent at the moment. |
| `OPENRBI_AGENT_NODE_NAME` | `default-node` | Stable name of this node's worker entry. Give every node its own. |
| `OPENRBI_AGENT_DOCKER_BASE_URL` | `unix:///var/run/docker.sock` | Docker API the agent creates sandboxes with. |
| `OPENRBI_AGENT_SANDBOX_IMAGE` | `openrbi-browser:latest` | Browser sandbox image. |
| `OPENRBI_AGENT_SANDBOX_COMMAND` | *(unset)* | Command override for the sandbox image, as a JSON list. Unset uses the image's own entrypoint. |
| `OPENRBI_AGENT_SANDBOX_NETWORK_NAME` | `openrbi_browser-plane` | Docker network sandboxes are attached to. Matches the default Compose project name; change it with a different project name. |
| `OPENRBI_AGENT_CAPACITY` | *(unset)* | Upper limit for the session slots this node reports. Unset means the computed value from free RAM and CPU ([deployment.md](deployment.md#sizing)). |
| `OPENRBI_AGENT_RESERVED_RAM_MB` | `512` | RAM kept free for the host and Docker when computing capacity. |
| `OPENRBI_AGENT_CAPACITY_RECOVERY_POLLS` | `3` | A higher capacity is reported only after this many consecutive polls confirm it; a drop applies at once. |
| `OPENRBI_AGENT_DEFAULT_CPU_LIMIT` | `2.0` | CPUs per sandbox unless the session's policy sets a value. |
| `OPENRBI_AGENT_DEFAULT_RAM_LIMIT_MB` | `2048` | RAM per sandbox. |
| `OPENRBI_AGENT_DEFAULT_PID_LIMIT` | `512` | Process limit per sandbox. |
| `OPENRBI_AGENT_DEFAULT_DISK_LIMIT_MB` | `2048` | Disk limit per sandbox. |
| `OPENRBI_AGENT_DEFAULT_SCREEN_WIDTH` | `1280` | Sandbox screen width in pixels. |
| `OPENRBI_AGENT_DEFAULT_SCREEN_HEIGHT` | `800` | Sandbox screen height in pixels. |
| `OPENRBI_AGENT_ENROLLMENT_TOKEN` | *(empty)* | Multi-node only: single-use token from **Workers → Register node**. When set, the agent enrolls itself at startup ([deployment.md](deployment.md#multi-node--experimental--technology-preview-not-a-complete-production-guide)). |
| `OPENRBI_AGENT_CONTROL_PLANE_URL` | `http://backend:8000` | Multi-node only: where the agent enrolls. Must reach an `admin` or `both` listener. |

## Frontend build

Build-time settings for the portal images (`frontend/user/.env`, `frontend/admin/.env`, or the environment of the build). See [deployment.md](deployment.md#user-portal-and-admin-portal-origins).

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | Base URL the portal sends API requests to. |
| `OPENRBI_ADMIN_BASE_PATH` | `/admin/` | Path the Admin Portal is served under; `/` for its own origin. Read from the environment or `frontend/admin/.env`. |
| `OPENRBI_DEV_API_TARGET` | `http://localhost:8080` | `npm run dev` only: the running stack's reverse proxy the dev servers send `/api` to ([development.md](development.md#frontend-development)). |

## Operator scripts

Optional overrides for the scripts in `scripts/`, set in the shell that runs them.

| Variable | Default | Description |
|---|---|---|
| `OPENRBI_BACKEND_CONTAINER` | `openrbi-backend-1` | Backend container used by `backup.sh`, `deploy.sh`, `reset-local-password.sh`, `rotate-totp-key.sh` and others. |
| `OPENRBI_POSTGRES_CONTAINER` | `openrbi-postgres-1` | Postgres container used by `backup.sh`, `restore.sh`, `deploy.sh` and `provision-segmented-db-roles.sh`. |
| `OPENRBI_ENV_FILE` | `.env` (checkout) | `.env` file `setup-network-isolation.sh` and `provision-segmented-db-roles.sh` read settings from. |
| `COMPOSE_PROJECT_NAME` | checkout directory name | Compose project; `setup-network-isolation.sh` derives the network name `<project>_browser-plane` from it. |
| `OPENRBI_BROWSER_PLANE_NETWORK` | `<project>_browser-plane` | Docker network `setup-network-isolation.sh` protects, if it isn't named after the project. |
| `OPENRBI_NETWORK_ISOLATION_MARKER_DIR` | `/var/lib/openrbi/network-isolation` | Host directory the isolation marker is written to (mounted into the backend). |
| `OPENRBI_SYSTEMD_UNIT_DIR` | `/etc/systemd/system` | Where `install-network-isolation-timer.sh` installs the systemd units. |

Container names assume the checkout directory is called `OpenRBI` (Compose names containers `<project>-<service>-1`). With a different directory name, set `COMPOSE_PROJECT_NAME=openrbi` in `.env` or override the container variables above.
