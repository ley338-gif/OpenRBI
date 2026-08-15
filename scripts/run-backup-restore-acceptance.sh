#!/bin/sh
# Destructive only to its dedicated Compose project. Exercises the real
# backup.sh and restore.sh against the current migrated schema.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PROJECT="${OPENRBI_BACKUP_RESTORE_PROJECT:-openrbi-backup-restore-acceptance}"
ENV_FILE="$REPO_ROOT/.env"
BROWSER_NETWORK="${PROJECT}_browser-plane"
MANIFEST=/tmp/openrbi-backup-restore-manifest.json
ENV_CREATED=0
ISOLATION_APPLIED=0
BACKUP_DIR=""

compose() {
    docker compose --project-name "$PROJECT" --project-directory "$REPO_ROOT" -f "$REPO_ROOT/docker-compose.yml" "$@"
}

cleanup() {
    if [ "$ISOLATION_APPLIED" -eq 1 ]; then
        sudo "$SCRIPT_DIR/setup-network-isolation.sh" --remove >/dev/null 2>&1 || true
    fi
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    if [ "$ENV_CREATED" -eq 1 ]; then
        rm -f -- "$ENV_FILE"
    fi
    if [ -n "$BACKUP_DIR" ]; then
        rm -rf -- "$BACKUP_DIR"
    fi
}
trap cleanup EXIT INT TERM

if [ "$(uname -s)" != "Linux" ]; then
    echo "backup/restore acceptance requires a real Linux Docker host" >&2
    exit 1
fi
for command in docker openssl curl sudo gzip tar mktemp; do
    command -v "$command" >/dev/null 2>&1 || { echo "missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null
if [ -e "$ENV_FILE" ]; then
    echo "$ENV_FILE already exists; acceptance never overwrites deployment secrets" >&2
    exit 1
fi
if docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | grep -q .; then
    echo "Compose project $PROJECT already exists; acceptance requires an empty project scope" >&2
    exit 1
fi

umask 077
POSTGRES_PASSWORD="$(openssl rand -hex 32)"
AGENT_TOKEN="$(openssl rand -hex 32)"
cat > "$ENV_FILE" <<EOF
POSTGRES_USER=openrbi
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=openrbi
OPENRBI_ENVIRONMENT=development
OPENRBI_DATABASE_URL=postgresql+asyncpg://openrbi:$POSTGRES_PASSWORD@postgres:5432/openrbi
OPENRBI_REDIS_URL=redis://redis:6379/0
OPENRBI_SESSION_AGENT_BASE_URL=http://session-agent:8100
OPENRBI_SESSION_AGENT_API_TOKEN=$AGENT_TOKEN
OPENRBI_TOTP_SECRET_ENCRYPTION_KEY=$(openssl rand -hex 32)
OPENRBI_CSRF_SECRET_KEY=$(openssl rand -hex 32)
OPENRBI_LDAP_BIND_PASSWORD=$(openssl rand -hex 32)
OPENRBI_AGENT_API_TOKEN=$AGENT_TOKEN
OPENRBI_AGENT_NODE_NAME=backup-restore-acceptance-node
OPENRBI_AGENT_SANDBOX_NETWORK_NAME=$BROWSER_NETWORK
OPENRBI_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)
EOF
ENV_CREATED=1
BACKUP_DIR="$(mktemp -d)"

compose config --quiet
compose build
compose up -d postgres redis clamav
for attempt in $(seq 1 60); do
    compose exec -T postgres pg_isready -U openrbi >/dev/null 2>&1 && break
    [ "$attempt" -lt 60 ] || { echo "PostgreSQL did not become ready" >&2; exit 1; }
    sleep 1
done
compose run --rm backend alembic upgrade head
docker build -t openrbi-browser:latest -f "$REPO_ROOT/docker/browser/Dockerfile" "$REPO_ROOT/docker/browser"
compose up -d
for attempt in $(seq 1 60); do
    if compose exec -T backend python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1; then
        break
    fi
    [ "$attempt" -lt 60 ] || { compose logs backend >&2; echo "Backend did not become ready" >&2; exit 1; }
    sleep 1
done

sudo env OPENRBI_BROWSER_PLANE_NETWORK="$BROWSER_NETWORK" "$SCRIPT_DIR/setup-network-isolation.sh"
ISOLATION_APPLIED=1

BACKEND_CONTAINER="$(compose ps -q backend)"
POSTGRES_CONTAINER="$(compose ps -q postgres)"
SETUP_TOKEN="$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep -A2 'initial setup token' | tail -1 | tr -d ' \r')"
[ -n "$SETUP_TOKEN" ] || { echo "initial setup token not found" >&2; exit 1; }
docker cp "$SCRIPT_DIR/fresh-install-acceptance.py" "$BACKEND_CONTAINER:/tmp/fresh-install-acceptance.py"
compose exec -T backend python /tmp/fresh-install-acceptance.py "$SETUP_TOKEN"
docker cp "$SCRIPT_DIR/backup-restore-acceptance.py" "$BACKEND_CONTAINER:/tmp/backup-restore-acceptance.py"
compose exec -T -e PYTHONPATH=/app backend python /tmp/backup-restore-acceptance.py seed "$MANIFEST"
echo "ACCEPT BR-03 exact baseline table counts and evidence identifiers recorded outside the backup"

OPENRBI_POSTGRES_CONTAINER="$POSTGRES_CONTAINER" \
OPENRBI_BACKEND_CONTAINER="$BACKEND_CONTAINER" \
    "$SCRIPT_DIR/backup.sh" "$BACKUP_DIR"
DB_DUMP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'openrbi-db-*.sql.gz' -print)"
QUARANTINE_TAR="$(find "$BACKUP_DIR" -maxdepth 1 -name 'openrbi-quarantine-*.tar.gz' -print)"
[ -n "$DB_DUMP" ] && [ -n "$QUARANTINE_TAR" ]
gzip -t "$DB_DUMP"
tar -tzf "$QUARANTINE_TAR" >/dev/null
echo "ACCEPT BR-02 real database and quarantine backup artifacts created and validated"

compose exec -T -e PYTHONPATH=/app backend python /tmp/backup-restore-acceptance.py corrupt "$MANIFEST"

printf 'yes\n' | COMPOSE_PROJECT_NAME="$PROJECT" \
    OPENRBI_POSTGRES_CONTAINER="$POSTGRES_CONTAINER" \
    "$SCRIPT_DIR/restore.sh" "$DB_DUMP" "$QUARANTINE_TAR"
echo "ACCEPT BR-05 destructive restore completed through the production restore script"

for attempt in $(seq 1 60); do
    if compose exec -T backend python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1; then
        break
    fi
    [ "$attempt" -lt 60 ] || { compose logs backend reverse-proxy >&2; echo "Restored backend did not become ready" >&2; exit 1; }
    sleep 1
done
compose exec -T -e PYTHONPATH=/app backend python /tmp/backup-restore-acceptance.py verify-data "$MANIFEST"
compose exec -T -e PYTHONPATH=/app backend python /tmp/backup-restore-acceptance.py verify-functional "$MANIFEST"

curl --fail --silent --show-error http://localhost:8080/health >/dev/null
curl --fail --silent --show-error http://localhost:8080/ >/dev/null
curl --fail --silent --show-error http://localhost:8080/admin/ >/dev/null
echo "ACCEPT BR-10 reverse proxy and both restored portals respond successfully"

if docker ps -q --filter label=openrbi.managed=true | grep -q .; then
    echo "a managed browser sandbox remained after restored-session termination" >&2
    exit 1
fi
echo "backup/restore acceptance passed; exact database state, quarantine bytes, login, session, and proxy are functional"
