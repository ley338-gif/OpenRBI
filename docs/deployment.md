# Deployment

> Status: placeholder for Phase 22. Current scaffolding provides a `docker-compose.yml` with service definitions for backend, session-agent, frontend, postgres, redis, clamav, and a reverse proxy, but it is not yet a complete, hardened deployment. This document will cover: requirements, installation, Docker Compose usage, HTTPS/TLS setup, secrets provisioning (`.env`), persistent storage layout, firewall rules, backup, and update procedure.

## Current state

```bash
cp .env.example .env   # fill in real secrets — never commit .env
docker compose up -d --build
```

This brings up the scaffolded services for local development only. It is **not** a production-ready deployment yet — hardening (Phase 20), network isolation (Phase 9), and the full security test suite (Phase 21) must land first.
