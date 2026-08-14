# ADR 0020: Redis → Valkey

## Status

Accepted

## Context

`docker-compose.yml` pinned `redis:7-alpine`, which was verified during Phase 23's documentation review (`DEPENDENCIES.md`) to actually resolve to Redis `7.4.10` — a version published by Redis Ltd under the post-relicense **RSALv2/SSPLv1** dual license, not the older BSD-3-Clause terms every earlier Redis release used. That combination requires a legal review before any redistribution or commercial use of OpenRBI as-is, which was left as an explicit open item rather than silently accepted or worked around with an unreviewed license interpretation.

OpenRBI's actual usage of this component is narrow and entirely protocol-level: transient session state, MFA-pending state, login-lockout counters, and single-use file-release tokens (`app/core/sessions.py`, `app/core/release_tokens.py`), via the standard `redis.asyncio` Python client talking `SET`/`GET`/`DELETE`/`SCAN`/`INCR`/`EXPIRE`/`TTL`/`GETDEL`/`PING`. Nothing in this project depends on a Redis-specific module, Lua scripting, cluster mode, or any behavior beyond that command set — the exact profile a Redis-protocol-compatible fork is meant to serve as a drop-in replacement for.

## Decision

Replace `docker-compose.yml`'s `redis` service image with `valkey/valkey:8-alpine` — Valkey, the Linux Foundation-governed, BSD-3-Clause-licensed fork of Redis (forked from the last BSD-licensed Redis release line). The service/hostname stays named `redis`: `OPENRBI_REDIS_URL` (`.env.example`), `app/core/redis.py`'s client construction, the `redis` health-check component name (`app/services/health.py`), and the e2e assertion for it (`frontend/e2e/tests/admin-portal.spec.ts`) are all unchanged — only the container image backing that service changed, not any application-facing name or config key.

Before switching, every command this project actually issues was verified directly against a running `valkey/valkey:8-alpine` container (`valkey-cli`, not assumed from documentation): `PING`, `SET ... EX`, `GETDEL`, `GET`, `INCR`, `EXPIRE`, `TTL`, `SCAN` — all behave identically to Redis. `GETDEL` specifically (the primitive behind `release_tokens.py`'s single-use download tokens) was checked deliberately, since it's a comparatively newer Redis command (added in Redis 6.2) and the kind of addition a fork could plausibly have not carried forward; Valkey supports it identically. The running container reports `valkey_version:8.1.9` and `redis_version:7.2.4` (the latter is Valkey's own declared protocol-compatibility version, used by clients that sniff server version).

## Alternatives Considered

- **Get a legal opinion on the RSALv2/SSPLv1 terms and keep Redis** — possible, but defers a decision this project can sidestep entirely at zero functional cost, for a component used in the narrowest possible way (no dependency on anything Redis-specific).
- **KeyDB or another Redis-protocol-compatible store** — also BSD/permissively licensed historically, but Valkey has the more clearly established governance (Linux Foundation, with the original Redis maintainers' involvement) and is the fork explicitly already named as the intended mitigation in `DEPENDENCIES.md` before this ADR existed.
- **Drop the pinned major/minor and just track `redis:alpine`/`latest`** — rejected independently of the license question: this project pins every image version deliberately (see `DEPENDENCIES.md`'s verification convention), and an unpinned tag reintroduces the same "what version is actually running" ambiguity that caused the original RSALv2/SSPLv1 issue to go unnoticed.

## Consequences

- The RSALv2/SSPLv1 legal-review open item in `DEPENDENCIES.md` is resolved, not just deferred — no further action needed before distribution on this specific point.
- No application code changed: `app/core/redis.py`, `app/core/sessions.py`, `app/core/release_tokens.py`, and `app/services/health.py` are all untouched, since the client library and protocol are identical.
- Anyone deploying OpenRBI from an older checkout who runs `docker compose pull` will start pulling `valkey/valkey:8-alpine` instead of `redis:7-alpine` on their next update — no data migration is needed since Valkey reads/writes the same RDB/AOF format for this compatibility generation, but this is still a container image change worth calling out in `CHANGELOG.md`.
- Should a future need arise for a genuinely Redis-specific feature Valkey doesn't carry forward, that would need its own ADR superseding this one — not expected given the project's current narrow usage, but not ruled out either.
