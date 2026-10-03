#!/bin/sh
# Writes the .env for the CI integration stacks (ci.yml's backend and LDAP
# integration jobs, acceptance-published.yml). CI runners only: it sizes the
# Session Agent for a runner, not for production.
set -eu
cd "$(dirname "$0")/.."

# Phase 20's fail-closed startup check rejects .env.example's literal
# placeholder secrets (docs/security-model.md), so a plain
# `cp .env.example .env` would never actually boot — generate real random
# values for every secret CI needs instead. DB_PASSWORD is substituted into
# both POSTGRES_PASSWORD and the embedded credential in OPENRBI_DATABASE_URL
# so they still match.
cp .env.example .env
DB_PASSWORD=$(openssl rand -hex 32)
sed -i "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=${DB_PASSWORD}#" .env
sed -i "s#^OPENRBI_DATABASE_URL=.*#OPENRBI_DATABASE_URL=postgresql+asyncpg://openrbi:${DB_PASSWORD}@postgres:5432/openrbi#" .env
# OPENRBI_SESSION_AGENT_API_TOKEN (backend, the token it sends) and
# OPENRBI_AGENT_API_TOKEN (session-agent, what it validates incoming requests
# against) must be the *same* shared secret — see CHANGELOG's Hardening entry
# for the real bug this exact mismatch caused when both sides silently
# matched on the placeholder instead.
AGENT_TOKEN=$(openssl rand -hex 32)
sed -i "s#^OPENRBI_SESSION_AGENT_API_TOKEN=.*#OPENRBI_SESSION_AGENT_API_TOKEN=${AGENT_TOKEN}#" .env
sed -i "s#^OPENRBI_AGENT_API_TOKEN=.*#OPENRBI_AGENT_API_TOKEN=${AGENT_TOKEN}#" .env
sed -i "s#^OPENRBI_TOTP_SECRET_ENCRYPTION_KEY=.*#OPENRBI_TOTP_SECRET_ENCRYPTION_KEY=$(openssl rand -hex 32)#" .env
sed -i "s#^OPENRBI_CSRF_SECRET_KEY=.*#OPENRBI_CSRF_SECRET_KEY=$(openssl rand -hex 32)#" .env
echo "OPENRBI_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)" >> .env

# Roadmap B3.1 (docs/roadmap-b3-capacity-autoscaling.md) — real capacity is
# derived from the runner's actual free RAM/CPU. The integration suite's
# session-scoped test cleanup (tests/conftest.py) means several real sandbox
# containers can be alive at once across a full run, not just within one
# test — a ceiling alone (OPENRBI_AGENT_CAPACITY) can only ever *lower* an
# already-higher computed value, so it doesn't help when the computed value
# itself is the constraint. Shrinking the per-sandbox reservation the
# computation divides by restores the suite's headroom on a runner with
# finite RAM. 1024 MB is still a real, functional limit for a short-lived
# automated test's Firefox+Xvfb+x11vnc sandbox (verified against the real
# noVNC/canvas E2E path), just not full production sizing.
echo "OPENRBI_AGENT_CAPACITY=20" >> .env
echo "OPENRBI_AGENT_DEFAULT_RAM_LIMIT_MB=1024" >> .env
# CPU turned out to be the actual binding constraint on a real runner, not
# RAM. Roadmap B3.2 fixed CPU-derived capacity barely reacting to real load
# on a multi-core runner (psutil's 0-100 host-wide average was treated as if
# already scaled by core count); after that fix 0.5 no longer matched real
# accumulated test load (NoCapacityError in CI), so 0.2 lets the same real
# free CPU divide into enough sandbox slots.
echo "OPENRBI_AGENT_DEFAULT_CPU_LIMIT=0.2" >> .env
