#!/bin/sh
# Runs the Phase 21 pytest integration suite (backend/tests/) against the
# real, already-running docker compose stack — not a separate test
# database, and not mocks (see backend/tests/conftest.py's module docstring
# for why). Run `docker compose up -d` first.
#
# pytest/pytest-asyncio are dev-only dependencies (backend/pyproject.toml's
# [project.optional-dependencies].dev) and deliberately not baked into the
# production image, so this installs them into the already-running
# container on demand rather than requiring an image rebuild just to test.
#
# For the checks that need the Docker socket or stopping other containers
# (network isolation, isolate's real network-detach, scanner-outage
# fail-closed), see scripts/run-security-tests.sh instead — those cannot
# run inside the backend container by design (ADR 0005).
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# -u root only for this one-off dev-tooling install and file copy: the
# running backend process itself stays the non-root uid the container
# starts as (Phase 20 hardening, docker-compose.yml) — this exec session
# doesn't change that. tests/ is deliberately not baked into the image
# (backend/Dockerfile only COPYs app/migrations/alembic.ini) so the
# production image stays free of test code; copy it in on demand instead.
docker exec -u root "$BACKEND_CONTAINER" pip install --quiet ".[dev]"
# MSYS_NO_PATHCONV avoids Git-Bash-for-Windows rewriting the container-side
# /app path into a host path before it reaches docker; harmless elsewhere.
# Copied files land root-owned with the source's normal (world-readable)
# permissions, which is enough for the non-root "openrbi" user to read them
# — no chown needed, and cap_drop: [ALL] (Phase 20) means even `-u root`
# can't chown in this container anyway (no CAP_CHOWN), which is working
# exactly as intended.
MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" rm -rf /app/tests
docker cp "$SCRIPT_DIR/../backend/tests" "$BACKEND_CONTAINER:/app/tests"
docker cp "$SCRIPT_DIR/../backend/pyproject.toml" "$BACKEND_CONTAINER:/app/pyproject.toml"
docker exec "$BACKEND_CONTAINER" pytest -v -p no:cacheprovider "$@"
