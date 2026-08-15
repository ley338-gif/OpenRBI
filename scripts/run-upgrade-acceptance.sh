#!/bin/sh
# Upgrade a persistent 0.1.1 installation at the pinned baseline commit to
# the current checkout. Destructive only to its dedicated Compose project.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
BASELINE_SHA="2816cfadbcfbf580959b1e78190fd7bbbe47796b"
PROJECT="${OPENRBI_UPGRADE_PROJECT:-openrbi-upgrade-acceptance}"
ENV_FILE="$REPO_ROOT/.env"
BROWSER_NETWORK="${PROJECT}_browser-plane"
CONTAINER_MANIFEST=/tmp/openrbi-upgrade-manifest.json
WORK_DIR=""
BASE_DIR=""
BACKUP_DIR=""
ENV_CREATED=0
ISOLATION_APPLIED=0

base_compose() {
    docker compose --project-name "$PROJECT" --project-directory "$BASE_DIR" -f "$BASE_DIR/docker-compose.yml" "$@"
}

target_compose() {
    docker compose --project-name "$PROJECT" --project-directory "$REPO_ROOT" -f "$REPO_ROOT/docker-compose.yml" "$@"
}

remove_isolation() {
    if [ "$ISOLATION_APPLIED" -eq 1 ]; then
        sudo "$SCRIPT_DIR/setup-network-isolation.sh" --remove >/dev/null 2>&1 || true
        ISOLATION_APPLIED=0
    fi
}

cleanup() {
    remove_isolation
    target_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    if [ "$ENV_CREATED" -eq 1 ]; then
        rm -f -- "$ENV_FILE"
    fi
    if [ -n "$WORK_DIR" ]; then
        rm -rf -- "$WORK_DIR"
    fi
}
trap cleanup EXIT INT TERM

if [ "$(uname -s)" != "Linux" ]; then
    echo "upgrade acceptance requires a real Linux Docker host" >&2
    exit 1
fi
for command in docker git openssl curl sudo gzip tar mktemp; do
    command -v "$command" >/dev/null 2>&1 || { echo "missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null
if [ -e "$ENV_FILE" ]; then
    echo "$ENV_FILE already exists; upgrade acceptance never overwrites deployment secrets" >&2
    exit 1
fi
git -C "$REPO_ROOT" cat-file -e "$BASELINE_SHA^{commit}"
git -C "$REPO_ROOT" merge-base --is-ancestor "$BASELINE_SHA" HEAD
if docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | grep -q .; then
    echo "Compose project $PROJECT already exists; acceptance requires an empty project scope" >&2
    exit 1
fi

umask 077
WORK_DIR="$(mktemp -d)"
BASE_DIR="$WORK_DIR/v0.1.1"
BACKUP_DIR="$WORK_DIR/pre-upgrade-backup"
HOST_MANIFEST="$WORK_DIR/upgrade-manifest.json"
BASE_ARCHIVE="$WORK_DIR/v0.1.1.tar"
mkdir -p "$BASE_DIR" "$BACKUP_DIR"
git -C "$REPO_ROOT" archive --format=tar --output="$BASE_ARCHIVE" "$BASELINE_SHA"
tar -xf "$BASE_ARCHIVE" -C "$BASE_DIR"

POSTGRES_PASSWORD="$(openssl rand -hex 32)"
AGENT_TOKEN="$(openssl rand -hex 32)"
TOTP_KEY="$(openssl rand -hex 32)"
write_env() {
    cat > "$1" <<EOF
POSTGRES_USER=openrbi
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=openrbi
OPENRBI_ENVIRONMENT=development
OPENRBI_DATABASE_URL=postgresql+asyncpg://openrbi:$POSTGRES_PASSWORD@postgres:5432/openrbi
OPENRBI_REDIS_URL=redis://redis:6379/0
OPENRBI_SESSION_AGENT_BASE_URL=http://session-agent:8100
OPENRBI_SESSION_AGENT_API_TOKEN=$AGENT_TOKEN
OPENRBI_TOTP_SECRET_ENCRYPTION_KEY=$TOTP_KEY
OPENRBI_LDAP_BIND_PASSWORD=$(openssl rand -hex 32)
OPENRBI_AGENT_API_TOKEN=$AGENT_TOKEN
OPENRBI_AGENT_NODE_NAME=upgrade-acceptance-node
OPENRBI_AGENT_SANDBOX_NETWORK_NAME=$BROWSER_NETWORK
EOF
}
write_env "$ENV_FILE"
ENV_CREATED=1
write_env "$BASE_DIR/.env"

base_compose config --quiet
base_compose build
docker build -t openrbi-browser:latest -f "$BASE_DIR/docker/browser/Dockerfile" "$BASE_DIR/docker/browser"
base_compose up -d postgres redis clamav
for attempt in $(seq 1 60); do
    base_compose exec -T postgres pg_isready -U openrbi >/dev/null 2>&1 && break
    [ "$attempt" -lt 60 ] || { echo "0.x PostgreSQL did not become ready" >&2; exit 1; }
    sleep 1
done
base_compose run --rm backend alembic upgrade head
base_compose up -d
for attempt in $(seq 1 60); do
    if base_compose exec -T backend python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1; then
        break
    fi
    [ "$attempt" -lt 60 ] || { base_compose logs backend >&2; echo "0.x backend did not become ready" >&2; exit 1; }
    sleep 1
done
sudo env OPENRBI_BROWSER_PLANE_NETWORK="$BROWSER_NETWORK" "$SCRIPT_DIR/setup-network-isolation.sh"
ISOLATION_APPLIED=1

BASE_BACKEND="$(base_compose ps -q backend)"
BASE_POSTGRES="$(base_compose ps -q postgres)"
SETUP_TOKEN="$(docker logs "$BASE_BACKEND" 2>&1 | grep -A2 'initial setup token' | tail -1 | tr -d ' \r')"
[ -n "$SETUP_TOKEN" ] || { echo "0.x initial setup token not found" >&2; exit 1; }
docker cp "$SCRIPT_DIR/fresh-install-acceptance.py" "$BASE_BACKEND:/tmp/fresh-install-acceptance.py"
base_compose exec -T backend python /tmp/fresh-install-acceptance.py "$SETUP_TOKEN"
docker cp "$SCRIPT_DIR/backup-restore-acceptance.py" "$BASE_BACKEND:/tmp/backup-restore-acceptance.py"
docker cp "$SCRIPT_DIR/upgrade-acceptance.py" "$BASE_BACKEND:/tmp/upgrade-acceptance.py"
base_compose exec -T -e PYTHONPATH=/app backend \
    python /tmp/backup-restore-acceptance.py seed "$CONTAINER_MANIFEST"
base_compose exec -T -e PYTHONPATH=/app backend \
    python /tmp/upgrade-acceptance.py augment "$CONTAINER_MANIFEST"
docker cp "$BASE_BACKEND:$CONTAINER_MANIFEST" "$HOST_MANIFEST"
chmod 600 "$HOST_MANIFEST"

OPENRBI_POSTGRES_CONTAINER="$BASE_POSTGRES" OPENRBI_BACKEND_CONTAINER="$BASE_BACKEND" \
    sh "$BASE_DIR/scripts/backup.sh" "$BACKUP_DIR"
DB_DUMP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'openrbi-db-*.sql.gz' -print)"
QUARANTINE_TAR="$(find "$BACKUP_DIR" -maxdepth 1 -name 'openrbi-quarantine-*.tar.gz' -print)"
gzip -t "$DB_DUMP"
tar -tzf "$QUARANTINE_TAR" >/dev/null
echo "ACCEPT UP-02 pre-upgrade 0.x database and quarantine backup captured and validated"

BASE_REVISION="$(base_compose exec -T backend alembic current | awk 'NR == 1 { print $1 }')"
BASE_BACKEND_IMAGE="$(docker image inspect "${PROJECT}-backend:latest" --format '{{.Id}}')"
BASE_AGENT_IMAGE="$(docker image inspect "${PROJECT}-session-agent:latest" --format '{{.Id}}')"
BASE_FRONTEND_IMAGE="$(docker image inspect "${PROJECT}-frontend:latest" --format '{{.Id}}')"
BASE_BROWSER_IMAGE="$(docker image inspect openrbi-browser:latest --format '{{.Id}}')"

remove_isolation
base_compose down --remove-orphans
echo "ACCEPT UP-03 0.x containers removed while persistent volumes were retained"

target_compose config --quiet
target_compose build
docker build -t openrbi-browser:latest -f "$REPO_ROOT/docker/browser/Dockerfile" "$REPO_ROOT/docker/browser"
target_compose up -d postgres redis clamav
for attempt in $(seq 1 60); do
    target_compose exec -T postgres pg_isready -U openrbi >/dev/null 2>&1 && break
    [ "$attempt" -lt 60 ] || { echo "upgraded PostgreSQL did not become ready" >&2; exit 1; }
    sleep 1
done
target_compose run --rm backend alembic upgrade head
TARGET_REVISION="$(target_compose run --rm backend alembic current | awk 'NR == 1 { print $1 }')"
TARGET_HEAD="$(target_compose run --rm backend alembic heads | awk 'NR == 1 { print $1 }')"
[ -n "$BASE_REVISION" ] && [ "$TARGET_REVISION" = "$TARGET_HEAD" ]
echo "ACCEPT UP-04 Alembic upgraded from $BASE_REVISION to the single target head $TARGET_HEAD"

TARGET_BACKEND_IMAGE="$(docker image inspect "${PROJECT}-backend:latest" --format '{{.Id}}')"
TARGET_AGENT_IMAGE="$(docker image inspect "${PROJECT}-session-agent:latest" --format '{{.Id}}')"
TARGET_FRONTEND_IMAGE="$(docker image inspect "${PROJECT}-frontend:latest" --format '{{.Id}}')"
TARGET_BROWSER_IMAGE="$(docker image inspect openrbi-browser:latest --format '{{.Id}}')"
[ "$BASE_BACKEND_IMAGE" != "$TARGET_BACKEND_IMAGE" ]
[ "$BASE_AGENT_IMAGE" != "$TARGET_AGENT_IMAGE" ]
[ "$BASE_FRONTEND_IMAGE" != "$TARGET_FRONTEND_IMAGE" ]
[ "$BASE_BROWSER_IMAGE" != "$TARGET_BROWSER_IMAGE" ]

target_compose up -d
for attempt in $(seq 1 60); do
    if target_compose exec -T backend python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1; then
        break
    fi
    [ "$attempt" -lt 60 ] || { target_compose logs backend >&2; echo "upgraded backend did not become ready" >&2; exit 1; }
    sleep 1
done
sudo env OPENRBI_BROWSER_PLANE_NETWORK="$BROWSER_NETWORK" "$SCRIPT_DIR/setup-network-isolation.sh"
ISOLATION_APPLIED=1

TARGET_BACKEND="$(target_compose ps -q backend)"
docker cp "$SCRIPT_DIR/upgrade-acceptance.py" "$TARGET_BACKEND:/tmp/upgrade-acceptance.py"
docker cp "$HOST_MANIFEST" "$TARGET_BACKEND:$CONTAINER_MANIFEST"
target_compose exec -T -e PYTHONPATH=/app backend \
    python /tmp/upgrade-acceptance.py verify-data "$CONTAINER_MANIFEST"
target_compose exec -T -e PYTHONPATH=/app backend \
    python /tmp/upgrade-acceptance.py verify-functional "$CONTAINER_MANIFEST"

curl --fail --silent --show-error http://localhost:8080/health >/dev/null
curl --fail --silent --show-error http://localhost:8080/ >/dev/null
curl --fail --silent --show-error http://localhost:8080/admin/ >/dev/null
echo "ACCEPT UP-09 all four current images replaced the 0.x images; reverse proxy and both portals respond"

if docker ps -q --filter label=openrbi.managed=true | grep -q .; then
    echo "a managed browser sandbox remained after upgraded-session termination" >&2
    exit 1
fi
echo "upgrade acceptance passed from pinned 0.1.1 baseline $BASELINE_SHA to $(git -C "$REPO_ROOT" rev-parse HEAD)"
