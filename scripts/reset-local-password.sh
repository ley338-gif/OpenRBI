#!/bin/sh
# Break-glass reset of a LOCAL account's password, run on the Docker host —
# for when every admin is locked out of the Admin Portal (typically: the
# break-glass local ADMIN's own password is lost, its TOTP device is fine)
# and the only access left is SSH. See backend/scripts/reset_local_password.py's
# docstring for exactly what it does and doesn't touch (MFA is unchanged;
# LDAP accounts are refused). Fully audited: same reset_password() service
# function the Admin API uses, PASSWORD_RESET_BY_ADMIN security event.
#
# Usage:
#   ./scripts/reset-local-password.sh <username>            # prompts for the new password
#   ./scripts/reset-local-password.sh <username> --enable   # also re-enables a disabled account
#   printf '%s\n' "$NEW_PASSWORD" | ./scripts/reset-local-password.sh <username>   # non-interactive
#
# The password is never passed as an argument (shell history, process list).
# Segmented deployments: point this at the admin listener's container, e.g.
#   OPENRBI_BACKEND_CONTAINER=openrbi-backend-admin-1 ./scripts/reset-local-password.sh <username>
set -eu

BACKEND_CONTAINER="${OPENRBI_BACKEND_CONTAINER:-openrbi-backend-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

USERNAME="${1:?usage: $0 <username> [--enable]}"
shift

docker cp "$SCRIPT_DIR/../backend/scripts/reset_local_password.py" "$BACKEND_CONTAINER:/app/reset_local_password.py"

# Allocate a TTY only when we have one, so the in-container getpass prompt
# works interactively and a piped password still works non-interactively.
TTY_FLAG=""
if [ -t 0 ]; then
    TTY_FLAG="-t"
fi

# MSYS_NO_PATHCONV: same Git-Bash-for-Windows guard as scripts/rotate-totp-key.sh.
STATUS=0
MSYS_NO_PATHCONV=1 docker exec -i $TTY_FLAG "$BACKEND_CONTAINER" python /app/reset_local_password.py "$USERNAME" "$@" || STATUS=$?

MSYS_NO_PATHCONV=1 docker exec -u root "$BACKEND_CONTAINER" rm -f /app/reset_local_password.py

exit "$STATUS"
