# Troubleshooting

> Start any investigation with `GET /admin/health` (ADMIN/SECURITY_REVIEWER) — it independently checks every dependency (API, PostgreSQL, Redis, Session Agent, sandbox runtime, browser-image availability, ClamAV, quarantine storage) and tells you which one is actually down, rather than guessing from symptoms. See [admin-guide.md#health-monitoring](admin-guide.md#health-monitoring).

## File scanner (ClamAV) unavailable

`GET /admin/health` reports `clamav: UNAVAILABLE` when ClamAV can't be reached or doesn't respond to `PING`. While this is true, **no download or upload is ever released**, regardless of what policy would otherwise allow — a scanner outage fails closed to `QUARANTINED`/blocked, never to an implicit clean result (`app/services/scanning.py`, [ADR 0008](adr/0008-fail-closed.md)). This is by design, not a bug: check `docker logs openrbi-clamav-1` and confirm the container is actually up and its virus database finished loading (the official image reports `healthy` in `docker ps` once it has) before assuming anything else is wrong. Files that were blocked purely because of the outage are not automatically retried — they stay `QUARANTINED` and can be manually reviewed/released once the scanner is back (see [quarantine.md](quarantine.md)); the pipeline itself does not distinguish "outage" from "infected" in the row's final status, only in the security-event `reason` metadata and the `Incident` it may have opened.

## Quarantine storage issues

`GET /admin/health`'s `quarantine_storage` check is a real write-and-delete probe against the staging directory (`app/services/health.py`), not just a path-exists check — so `UNAVAILABLE` here means the backend genuinely cannot write to `/app/data/staging` (disk full, the `quarantine-staging` volume not mounted, a permissions problem). Since every download is staged to disk before it's ever scanned, this failure mode blocks downloads at the same point a scanner outage would, for the same fail-closed reason. Check `docker exec openrbi-backend-1 df -h /app/data` for disk space and `docker volume inspect openrbi_quarantine-staging` to confirm the volume exists and is mounted where `docker-compose.yml` expects.

## Database / Redis operational issues

`GET /admin/health`'s `postgres` check is a real `SELECT 1`; `redis` is a real `PING`. If either is `UNAVAILABLE`, note that `/admin/health` itself requires a DB-backed session to authenticate — so a full PostgreSQL outage takes `/admin/health` down with it, same as every other admin endpoint. The plain unauthenticated `GET /health` liveness probe has no such dependency and stays reachable regardless, which is the one signal you can trust to tell "the process is up" apart from "the process can do anything useful" (see [architecture.md#health-monitoring-phase-19](architecture.md#health-monitoring-phase-19)). A Redis outage specifically breaks login (sessions and MFA-pending state are Redis-backed, not JWTs — see [security-model.md](security-model.md)) even while PostgreSQL and the API are otherwise fine, which is why `/admin/health` checks it as a distinct component rather than folding it into a generic "backend is up" signal.

## Reverse proxy returns 502 after rebuilding a service

nginx resolves `proxy_pass` upstream hostnames (`backend`, `frontend`) to an IP once, when its worker processes start — it does not re-resolve them automatically when a container is recreated with a new IP (e.g. after `docker compose up -d --build backend`). Fix: restart the reverse proxy after rebuilding any service it proxies to:

```bash
docker compose restart reverse-proxy
```

## Secure Browser session fails to connect right after starting

If `POST /sessions` succeeds but the noVNC connection immediately fails, the sandbox's VNC server likely hadn't started listening yet — this is a real, intermittent timing gap between the container starting and its entrypoint (Xvfb → x11vnc) actually binding the display port. `app/services/sessions.py`'s `_wait_for_display_ready` already retries this before reporting a session `ACTIVE`; if it still happens, check the Session Agent's logs for the sandbox in question and consider raising the retry count/timeout there.

## Session Agent unreachable

Backend endpoints touching sessions (`POST /sessions`, the display WebSocket) return `502`/`503` with a `session agent unreachable` or similar detail if `OPENRBI_SESSION_AGENT_BASE_URL`/`OPENRBI_SESSION_AGENT_API_TOKEN` are misconfigured, or the `session-agent` container isn't running. Check `docker logs openrbi-session-agent-1` and confirm the token matches `OPENRBI_AGENT_API_TOKEN` in the Session Agent's own environment — see `.env.example`'s comments on keeping these two in sync.

## Browser sandbox won't start

Confirm the hardened browser image actually exists (`docker images | grep openrbi-browser`) — it's not a compose service, so `docker compose up` never builds it; run `./scripts/build-browser-image.sh` first (see docs/deployment.md).

## Portal: login fails

A wrong password, an unknown username, and a disabled account all show the identical "invalid credentials" message in both portals — by design (see [user-guide.md#logging-in](user-guide.md#logging-in)), not a bug to fix. If login fails even with correct credentials, check for a `429` in the browser's network tab: ten wrong attempts against a username locks it out for 15 minutes (`LOGIN_LOCKED` security event, see [security-model.md#login-brute-force-protection-phase-20](security-model.md#login-brute-force-protection-phase-20)) — the *correct* password won't work either until the window clears. If the request never reaches the backend at all (a network error, not a `401`), see "User API unavailable" / "Admin API unavailable" below.

## Portal: MFA enrollment fails ("that code didn't work")

The most common cause is clock drift between the server and the device running the authenticator app — TOTP codes are time-windowed and don't tolerate more than roughly ±30-60 seconds of skew. Confirm the backend container's clock is correct (`docker exec openrbi-backend-1 date -u`) before assuming the QR code or secret is wrong. A stuck "Confirm and continue" spinner with no error at all instead usually means the backend is unreachable — check the Network tab for a failed `POST /mfa/setup/confirm`.

## Portal: Secure Browser stuck at "Preparing sandbox…" or "Waiting for capacity…"

The User Portal polls `GET /sessions/{id}` once a second and only advances once the session's real status changes — it never fabricates progress. "Waiting for capacity…" (`QUEUED`) staying up for a long time means no browser-node capacity is free; check `GET /admin/nodes` (Admin Portal → System) for whether the node is drained or already at its session limit. "Preparing sandbox…" (`STARTING`) staying up means the Session Agent hasn't reported the sandbox as ready yet — see "Session Agent unreachable" and "Browser sandbox won't start" above; check `docker logs openrbi-session-agent-1` for the specific session ID shown under the portal's status line.

## Portal: noVNC cannot connect ("Connecting display…" never finishes)

First check the browser console/network tab for a WebSocket attempt to `/api/display/{id}/ws` at all:

- **No WebSocket attempt is made**: this was a real, since-fixed frontend bug (a React ref-timing race — the display connection was attempted before the viewer's container `<div>` had actually mounted). If seen on a build predating the fix in [ADR 0014](adr/0014-separate-user-and-admin-portal-frontends.md), rebuild the User Portal from current `main`.
- **A WebSocket attempt is made but fails/closes immediately**: see "Secure Browser session fails to connect right after starting" above — the sandbox's VNC server may not have bound its port yet; also confirm the backend's `browser-plane` leg is actually exempted by `scripts/setup-network-isolation.sh` (Compact: the default `172.30.0.2`; Segmented: see [deployment.md#user-portal-and-admin-portal-origins](deployment.md#user-portal-and-admin-portal-origins) for the `OPENRBI_BACKEND_BROWSER_PLANE_IP` override needed when running `backend-user`).

## Portal: "End Session" shows Terminated but the session later reappears as Disconnected

A known, unfixed backend limitation, not a frontend bug: destroying the sandbox container (which `terminate_session` does) also kills the VNC TCP connection the display WebSocket handler is independently watching, and that handler's own `finally` block can write `DISCONNECTED` back over the session row concurrently with (or just after) `terminate_session`'s own `TERMINATED` write — two independent server-side async tasks racing on the same row. The User Portal already sequences its own calls to minimize this (terminate before closing the display connection, see `frontend/user/src/pages/SecureBrowser.tsx`), but this alone cannot fully prevent a server-side race between two backend tasks. If seen, the session is not actually still running — `TERMINATED` (or `DISCONNECTED`, in this specific case) both mean the sandbox is gone; treat the persisted status here as a display-only inconsistency, not a live session, and start a new one as usual.

## Portal: User API unavailable

The User Portal shows a generic backend-unavailable banner (not a raw network error or a blank page) if any request fails to reach the User listener at all. Confirm the process serving `VITE_API_BASE_URL` is actually up: in Compact, `docker compose ps backend`; in a Segmented deployment, `docker compose ps backend-user`. A `404` on every request (rather than a connection failure) instead usually means the portal is accidentally pointed at an `admin`-mode listener, which never registers session/file/display routes — double-check each app's own `.env`.

## Portal: Admin API unavailable

Same as above, but for `backend` (Compact) / `backend-admin` (Segmented). Since the Admin Portal itself requires an authenticated, MFA-verified session to reach almost anything, a fully down Admin API also takes `/admin/health` down with it — fall back to `GET /health` (unauthenticated liveness only) or the host-level `docker compose ps`/`docker logs` to distinguish "API process is down" from "API is up but something behind it isn't."

## Portal: download unavailable

The Downloads page's **Download** button requests a genuine single-use token (`POST /files/{id}/download-token`) and immediately follows it — a second click, or reusing a link from browser history, gets a `401` by design (the token was already consumed), not a bug. A file stuck showing "Awaiting review" instead of a Download button is still `QUARANTINED` — see [Quarantine review](admin-guide.md#quarantine-review) for the administrator side of releasing it.

## Portal: session isolated

The Secure Browser page shows this honestly (*"This session has been isolated by an administrator…"*) rather than a generic connection error — see [user-guide.md#secure-browser](user-guide.md#secure-browser). This is expected admin behavior, not a defect; end the session and start a new one.

## Portal: health page shows Degraded/Unavailable

See "File scanner (ClamAV) unavailable", "Quarantine storage issues", and "Database / Redis operational issues" above — the Admin Portal's System page renders exactly what `GET /admin/health` returns, component by component, with no hardcoded green checkmarks anywhere to mask a real outage.
