# Troubleshooting

> Status: populated as each subsystem ships. Planned topics still pending their phase: file scanner unavailable (Phase 14), quarantine storage issues (Phase 15), database/Redis operational issues (Phase 19 health monitoring).

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
