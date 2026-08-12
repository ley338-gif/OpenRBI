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
