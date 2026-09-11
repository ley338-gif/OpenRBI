#!/bin/sh
# Copies seed-standard-policies.py into the running backend container and
# runs it. Run `docker compose up -d` first.
#
# Safe to run more than once: the script skips any policy whose name
# already exists rather than erroring out.
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

docker cp "$SCRIPT_DIR/seed-standard-policies.py" "$BACKEND_CONTAINER:/app/seed_standard_policies.py"
MSYS_NO_PATHCONV=1 docker exec "$BACKEND_CONTAINER" python /app/seed_standard_policies.py
MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" rm -f /app/seed_standard_policies.py
