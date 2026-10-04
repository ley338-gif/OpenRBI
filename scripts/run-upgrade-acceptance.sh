#!/bin/sh
# Upgrade a persistent installation of a baseline version to the current
# checkout. Destructive only to its dedicated Compose project.
#
# OPENRBI_UPGRADE_BASELINE selects the baseline:
#   (unset)           the pinned 0.1.1 commit below — the oldest supported
#                     source of an upgrade to v1
#   previous-release  the newest GA tag (vX.Y.Z) in this checkout's history
#                     that does not point at the commit under test, i.e. the
#                     release users run today (1.0.2 → candidate)
#   <git ref>         any other tag or commit
# The baseline is built from its own source, as scripts/deploy.sh does; the
# fixture and verification helpers come from the current checkout and must
# keep working against the baseline's application code.
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
# shellcheck source=scripts/acceptance-images.sh
. "$SCRIPT_DIR/acceptance-images.sh"
PINNED_BASELINE_SHA="2816cfadbcfbf580959b1e78190fd7bbbe47796b"
BASELINE_REQUEST="${OPENRBI_UPGRADE_BASELINE:-$PINNED_BASELINE_SHA}"
if [ "$BASELINE_REQUEST" = previous-release ]; then
    # --no-contains HEAD skips a tag on the commit under test itself (an
    # acceptance run of a just-published release checks out that tag).
    BASELINE_REF="$(git -C "$REPO_ROOT" tag --merged HEAD --no-contains HEAD --list 'v*' --sort=-v:refname \
        | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n 1 || true)"
    [ -n "$BASELINE_REF" ] || { echo "no previous GA release tag (vX.Y.Z) in this checkout's history; fetch tags (fetch-depth: 0)" >&2; exit 1; }
    BASELINE_LABEL="$BASELINE_REF"
elif [ "$BASELINE_REQUEST" = "$PINNED_BASELINE_SHA" ]; then
    BASELINE_REF="$BASELINE_REQUEST"
    BASELINE_LABEL="0.1.1"
else
    BASELINE_REF="$BASELINE_REQUEST"
    BASELINE_LABEL="$BASELINE_REQUEST"
fi
BASELINE_SHA="$(git -C "$REPO_ROOT" rev-parse --verify "$BASELINE_REF^{commit}")"
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
BASE_DIR="$WORK_DIR/baseline"
BACKUP_DIR="$WORK_DIR/pre-upgrade-backup"
HOST_MANIFEST="$WORK_DIR/upgrade-manifest.json"
BASE_ARCHIVE="$WORK_DIR/baseline.tar"
mkdir -p "$BASE_DIR" "$BACKUP_DIR"
git -C "$REPO_ROOT" archive --format=tar --output="$BASE_ARCHIVE" "$BASELINE_SHA"
tar -xf "$BASE_ARCHIVE" -C "$BASE_DIR"
# umask 077 protects generated secrets below, but source files copied into
# non-root images must retain normal read/execute permissions.
chmod -R a+rX "$BASE_DIR"

POSTGRES_PASSWORD="$(openssl rand -hex 32)"
AGENT_TOKEN="$(openssl rand -hex 32)"
TOTP_KEY="$(openssl rand -hex 32)"
# The pinned 0.1.1 baseline ($BASE_DIR) predates RBI-POST-003 and has no
# such setting — harmless there (pydantic-settings ignores unrecognized
# OPENRBI_* env vars), but required for every v1 release and the current
# checkout ($REPO_ROOT) to boot at all. Same write_env() writes both on
# purpose (see below).
CSRF_KEY="$(openssl rand -hex 32)"
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
OPENRBI_CSRF_SECRET_KEY=$CSRF_KEY
OPENRBI_LDAP_BIND_PASSWORD=$(openssl rand -hex 32)
OPENRBI_AGENT_API_TOKEN=$AGENT_TOKEN
OPENRBI_AGENT_NODE_NAME=upgrade-acceptance-node
OPENRBI_AGENT_CAPACITY=20
OPENRBI_AGENT_DEFAULT_RAM_LIMIT_MB=1024
OPENRBI_AGENT_DEFAULT_CPU_LIMIT=0.5
OPENRBI_AGENT_SANDBOX_NETWORK_NAME=$BROWSER_NETWORK
OPENRBI_DOCKER_SOCKET_GID=$(stat -c '%g' /var/run/docker.sock)
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
    [ "$attempt" -lt 60 ] || { echo "baseline $BASELINE_LABEL PostgreSQL did not become ready" >&2; exit 1; }
    sleep 1
done
base_compose run --rm backend alembic upgrade head
base_compose up -d
for attempt in $(seq 1 60); do
    if base_compose exec -T backend python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" >/dev/null 2>&1; then
        break
    fi
    [ "$attempt" -lt 60 ] || { base_compose logs backend >&2; echo "baseline $BASELINE_LABEL backend did not become ready" >&2; exit 1; }
    sleep 1
done
sudo env OPENRBI_BROWSER_PLANE_NETWORK="$BROWSER_NETWORK" "$SCRIPT_DIR/setup-network-isolation.sh"
ISOLATION_APPLIED=1

BASE_BACKEND="$(base_compose ps -q backend)"
BASE_POSTGRES="$(base_compose ps -q postgres)"
SETUP_TOKEN="$(docker logs "$BASE_BACKEND" 2>&1 | grep -A2 'initial setup token' | tail -1 | tr -d ' \r')"
[ -n "$SETUP_TOKEN" ] || { echo "baseline $BASELINE_LABEL initial setup token not found" >&2; exit 1; }
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
echo "ACCEPT UP-02 pre-upgrade $BASELINE_LABEL database and quarantine backup captured and validated"

BASE_REVISION="$(base_compose exec -T backend alembic current | awk 'NR == 1 { print $1 }')"
BASE_BACKEND_IMAGE="$(docker image inspect "${PROJECT}-backend:latest" --format '{{.Id}}')"
BASE_AGENT_IMAGE="$(docker image inspect "${PROJECT}-session-agent:latest" --format '{{.Id}}')"
BASE_FRONTEND_IMAGE="$(docker image inspect "${PROJECT}-frontend:latest" --format '{{.Id}}')"
BASE_BROWSER_IMAGE="$(docker image inspect openrbi-browser:latest --format '{{.Id}}')"

remove_isolation
base_compose down --remove-orphans
echo "ACCEPT UP-03 $BASELINE_LABEL containers removed while persistent volumes were retained"

target_compose config --quiet
TARGET_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
TARGET_VERSION="$(tr -d ' \r\n' < "$REPO_ROOT/VERSION")"
TARGET_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if acceptance_images_enabled; then
    # The baseline above is still built from its own source; only the
    # upgrade target is the published release. The label checks below then
    # also prove the checkout matches the release (TARGET_SHA/VERSION).
    use_published_images "$PROJECT"
else
    target_compose build \
        --build-arg OPENRBI_VERSION="$TARGET_VERSION" \
        --build-arg OPENRBI_COMMIT_SHA="$TARGET_SHA" \
        --build-arg OPENRBI_BUILD_DATE="$TARGET_BUILD_DATE"
    docker build \
        --build-arg OPENRBI_VERSION="$TARGET_VERSION" \
        --build-arg OPENRBI_COMMIT_SHA="$TARGET_SHA" \
        --build-arg OPENRBI_BUILD_DATE="$TARGET_BUILD_DATE" \
        -t openrbi-browser:latest -f "$REPO_ROOT/docker/browser/Dockerfile" "$REPO_ROOT/docker/browser"
fi
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
for image in \
    "${PROJECT}-backend:latest" \
    "${PROJECT}-session-agent:latest" \
    "${PROJECT}-frontend:latest" \
    openrbi-browser:latest; do
    [ "$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$TARGET_SHA" ]
    [ "$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = "$TARGET_VERSION" ]
done
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
# Have the capability-free backend user create the secret-bearing manifest
# itself. docker cp would make it root-owned and cap_drop: ALL rightly blocks
# a subsequent chown, while broadening mode 0600 would expose the MFA seed.
docker exec -i "$TARGET_BACKEND" sh -c 'umask 077; cat > "$1"' sh \
    "$CONTAINER_MANIFEST" < "$HOST_MANIFEST"
target_compose exec -T -e PYTHONPATH=/app backend \
    python /tmp/upgrade-acceptance.py verify-data "$CONTAINER_MANIFEST"
target_compose exec -T -e PYTHONPATH=/app backend \
    python /tmp/upgrade-acceptance.py verify-functional "$CONTAINER_MANIFEST"

curl --fail --silent --show-error http://localhost:8080/health >/dev/null
curl --fail --silent --show-error http://localhost:8080/ >/dev/null
curl --fail --silent --show-error http://localhost:8080/admin/ >/dev/null
echo "ACCEPT UP-09 all four current images replaced the $BASELINE_LABEL images; reverse proxy and both portals respond"

if docker ps -q --filter label=openrbi.managed=true | grep -q .; then
    echo "a managed browser sandbox remained after upgraded-session termination" >&2
    exit 1
fi
echo "upgrade acceptance passed from baseline $BASELINE_LABEL ($BASELINE_SHA) to $(git -C "$REPO_ROOT" rev-parse HEAD)"
