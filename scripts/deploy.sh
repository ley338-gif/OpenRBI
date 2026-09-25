#!/bin/sh
# One command for a fresh install AND every update of a host (docs/deployment.md).
# Idempotent: re-running it on an up-to-date host changes nothing.
#
#   ./scripts/deploy.sh                 # control plane (docker-compose.yml)
#   ./scripts/deploy.sh --node          # additional worker node (docker-compose.node.yml)
#   ./scripts/deploy.sh --no-backup     # skip the pre-update backup
#   sudo ./scripts/deploy.sh            # also applies the network-isolation rules (needs root)
#
# Control plane, in the order docs/release/upgrade.md prescribes:
#   1. backup (only when a stack is already running, i.e. an update)
#   2. build images with real version metadata (scripts/build.sh)
#   3. start postgres/redis/clamav, run database migrations, start the rest
#   4. build the browser sandbox image (not a compose service)
#   5. restart reverse-proxy (nginx caches upstream container IPs)
#   6. seed standard policy templates that are new in this release
#   7. apply network isolation when run as root, otherwise say how
#
# Extra compose files (prod/segmented overlay): set COMPOSE_FILE in .env,
# e.g. COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml — docker
# compose itself honours it, so every step below uses the same stack.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

MODE=control
BACKUP=1
for arg in "$@"; do
    case "$arg" in
        --node) MODE=node ;;
        --no-backup) BACKUP=0 ;;
        -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not installed"
[ -f .env ] || die ".env is missing — copy .env.example to .env and fill in every required secret first (docs/deployment.md)"

# Required since v1.0.1 (docs/deployment.md#update-procedure): without it
# session-agent cannot reach the Docker socket.
if ! grep -q '^OPENRBI_DOCKER_SOCKET_GID=' .env && [ -S /var/run/docker.sock ]; then
    # GNU stat (Linux) first, BSD stat (macOS) as a fallback.
    gid="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || stat -f '%g' /var/run/docker.sock)"
    log "adding OPENRBI_DOCKER_SOCKET_GID=$gid to .env"
    printf '\nOPENRBI_DOCKER_SOCKET_GID=%s\n' "$gid" >> .env
fi

build_browser_image() {
    log "building browser sandbox image"
    "$SCRIPT_DIR/build-browser-image.sh"
}

network_isolation() {
    if [ "$(id -u)" -eq 0 ]; then
        log "applying network isolation rules"
        "$SCRIPT_DIR/setup-network-isolation.sh"
        if ! systemctl list-unit-files 2>/dev/null | grep -q '^openrbi-network-isolation\.timer'; then
            log "hint: ./scripts/install-network-isolation-timer.sh re-applies them automatically after Docker restarts"
        fi
    else
        log "NOT applied: network isolation needs root. Run: sudo ./scripts/setup-network-isolation.sh"
        log "(or run this whole script with sudo)"
    fi
}

if [ "$MODE" = node ]; then
    log "worker node: building and starting session-agent"
    docker compose -f docker-compose.node.yml up -d --build
    build_browser_image
    network_isolation
    log "done. A new node appears as PENDING under Admin Portal -> Workers until approved."
    exit 0
fi

# --- control plane ---------------------------------------------------------

UPDATE=0
if [ -n "$(docker compose ps -q postgres 2>/dev/null)" ]; then
    UPDATE=1
fi

if [ "$UPDATE" -eq 1 ] && [ "$BACKUP" -eq 1 ]; then
    log "existing installation found: taking a backup first (skip with --no-backup)"
    OPENRBI_POSTGRES_CONTAINER="$(docker compose ps -q postgres)" \
    OPENRBI_BACKEND_CONTAINER="$(docker compose ps -q backend)" \
        "$SCRIPT_DIR/backup.sh"
fi

log "building images"
"$SCRIPT_DIR/build.sh"

log "starting data services"
docker compose up -d postgres redis clamav
i=0
until docker compose exec -T postgres pg_isready -q >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -le 60 ] || die "postgres did not become ready within 120s"
    sleep 2
done

log "running database migrations"
docker compose run --rm -T backend alembic upgrade head

log "starting application services"
docker compose up -d
build_browser_image
docker compose restart reverse-proxy >/dev/null

log "waiting for the backend"
i=0
until docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -le 60 ] || die "backend did not become healthy within 120s — check: docker compose logs backend"
    sleep 2
done

log "seeding standard policy templates (only ones new to this installation)"
OPENRBI_BACKEND_CONTAINER="$(docker compose ps -q backend)" "$SCRIPT_DIR/seed-standard-policies.sh"

network_isolation

if docker compose exec -T backend python -c "
import asyncio
from app.db.session import async_session_factory
from app.services.setup_service import is_setup_required
async def main():
    async with async_session_factory() as db:
        raise SystemExit(0 if await is_setup_required(db) else 1)
asyncio.run(main())
" >/dev/null 2>&1; then
    log "first-run setup pending: open the Admin Portal and enter the setup token from"
    log "  docker compose logs backend | grep -A3 'initial setup token'"
    log "(the standard policy templates are created when setup completes)"
fi

log "done. Check the Admin Portal's System page (GET /admin/health) before reopening access."
