#!/bin/sh
# Destructive only to its dedicated Compose project. Run on a clean Linux
# Docker host/CI runner; it refuses to overwrite a repository .env file.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PROJECT="${OPENRBI_ACCEPTANCE_PROJECT:-openrbi-acceptance}"
ENV_FILE="$REPO_ROOT/.env"
BROWSER_NETWORK="${PROJECT}_browser-plane"
ENV_CREATED=0
ISOLATION_APPLIED=0

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
}
trap cleanup EXIT INT TERM

if [ "$(uname -s)" != "Linux" ]; then
    echo "fresh-install acceptance requires a real Linux Docker host" >&2
    exit 1
fi
for command in docker openssl curl sudo; do
    command -v "$command" >/dev/null 2>&1 || { echo "missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null
if [ -e "$ENV_FILE" ]; then
    echo "$ENV_FILE already exists; use a clean clone so acceptance never overwrites deployment secrets" >&2
    exit 1
fi
if docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | grep -q .; then
    echo "Compose project $PROJECT already exists; acceptance requires a clean environment" >&2
    exit 1
fi
echo "ACCEPT 01 clean host scope confirmed for project $PROJECT"

umask 077
POSTGRES_PASSWORD="$(openssl rand -hex 32)"
AGENT_TOKEN="$(openssl rand -hex 32)"
TOTP_KEY="$(openssl rand -hex 32)"
CSRF_KEY="$(openssl rand -hex 32)"
cat > "$ENV_FILE" <<EOF
POSTGRES_USER=openrbi
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=openrbi
OPENRBI_ENVIRONMENT=development
OPENRBI_DATABASE_URL=postgresql+asyncpg://openrbi:$POSTGRES_PASSWORD@postgres:5432/openrbi
OPENRBI_REDIS_URL=redis://redis:6379/0
OPENRBI_SESSION_AGENT_BASE_URL=http://session-agent:8100
OPENRBI_SESSION_AGENT_API_TOKEN=$AGENT_TOKEN
OPENRBI_TOTP_SECRET_ENCRYPTION_KEY=$TOTP_KEY
OPENRBI_CSRF_SECRET_KEY=$CSRF_KEY
OPENRBI_LDAP_BIND_PASSWORD=$(openssl rand -hex 32)
OPENRBI_AGENT_API_TOKEN=$AGENT_TOKEN
OPENRBI_AGENT_NODE_NAME=acceptance-node
OPENRBI_AGENT_CAPACITY=20
OPENRBI_AGENT_DEFAULT_RAM_LIMIT_MB=1024
OPENRBI_AGENT_SANDBOX_NETWORK_NAME=$BROWSER_NETWORK
OPENRBI_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)
EOF
ENV_CREATED=1
[ "$(stat -c '%a' "$ENV_FILE")" = "600" ]
echo "ACCEPT 02 private .env generated with mode 600"
[ "${#POSTGRES_PASSWORD}" -eq 64 ] && [ "${#AGENT_TOKEN}" -eq 64 ] && [ "${#TOTP_KEY}" -eq 64 ] && [ "${#CSRF_KEY}" -eq 64 ]
! grep -q 'changeme-generate-a-strong-secret' "$ENV_FILE"
echo "ACCEPT 03 independent strong secrets generated without placeholders"

compose config --quiet
compose build
echo "ACCEPT 04 all Compose application images built from source"

compose up -d postgres redis clamav
for attempt in $(seq 1 60); do
    compose exec -T postgres pg_isready -U openrbi >/dev/null 2>&1 && break
    [ "$attempt" -lt 60 ] || { echo "PostgreSQL did not become ready" >&2; exit 1; }
    sleep 1
done
echo "[fresh-install] base services ready"

compose run --rm backend alembic upgrade head
echo "ACCEPT 06 Alembic migrated a genuinely empty PostgreSQL volume"

docker build -t openrbi-browser:latest -f "$REPO_ROOT/docker/browser/Dockerfile" "$REPO_ROOT/docker/browser"
echo "ACCEPT 07 hardened browser sandbox image built"

compose up -d
for attempt in $(seq 1 60); do
    if compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1; then
        break
    fi
    [ "$attempt" -lt 60 ] || { compose logs backend >&2; echo "Backend did not become ready" >&2; exit 1; }
    sleep 1
done
curl --fail --silent --show-error http://localhost:8080/health >/dev/null
curl --fail --silent --show-error http://localhost:8080/ >/dev/null
curl --fail --silent --show-error http://localhost:8080/admin/ >/dev/null
echo "ACCEPT 05 complete Compact stack and both portals started"

sudo env OPENRBI_BROWSER_PLANE_NETWORK="$BROWSER_NETWORK" "$SCRIPT_DIR/setup-network-isolation.sh"
ISOLATION_APPLIED=1
sudo iptables -L DOCKER-USER -n | grep -q 'openrbi-network-isolation'
echo "ACCEPT 08 host network-isolation rules applied and observable"

BACKEND_CONTAINER="$(compose ps -q backend)"
SETUP_TOKEN="$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep -A2 'initial setup token' | tail -1 | tr -d ' \r')"
if [ -z "$SETUP_TOKEN" ]; then
    echo "initial setup token was not present in backend console logs" >&2
    exit 1
fi
docker cp "$SCRIPT_DIR/fresh-install-acceptance.py" "$BACKEND_CONTAINER:/tmp/fresh_install_acceptance.py"
compose exec -T -e OPENRBI_ACCEPT_CHECK_DISPLAY_PROXY=1 backend python /tmp/fresh_install_acceptance.py "$SETUP_TOKEN"

if docker ps -q --filter label=openrbi.managed=true | grep -q .; then
    echo "a managed browser sandbox remained after session termination" >&2
    docker ps --filter label=openrbi.managed=true >&2
    exit 1
fi

echo "fresh-install acceptance passed; cleanup will remove the dedicated project, volumes, firewall rules, and .env"
