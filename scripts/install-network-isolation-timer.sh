#!/bin/sh
# Installs scripts/systemd/openrbi-network-isolation.{service,timer} with
# WorkingDirectory set to *this* checkout's real path, then runs the
# service once and fails loudly if that run fails.
#
# Why this exists instead of "cp the unit files and edit WorkingDirectory":
# a hand-edited (or un-edited) WorkingDirectory that doesn't match the real
# checkout path — /opt/openrbi vs /opt/OpenRBI is enough on Linux — makes
# every timer-triggered run fail with status=200/CHDIR, while
# `systemctl list-timers` keeps showing the timer as perfectly healthy. If
# the script had been run once by hand beforehand, the health marker stays
# fresh long enough that /admin/system shows HEALTHY right after setup, and
# the failure only surfaces once that marker quietly goes stale.
#
# Usage (as root, on the Docker host, from anywhere):
#   sudo ./scripts/install-network-isolation-timer.sh
#   sudo ./scripts/install-network-isolation-timer.sh --uninstall
#
# Idempotent: re-run it after moving the checkout to rewrite the path.
set -eu

UNIT_DIR="${OPENRBI_SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
SERVICE=openrbi-network-isolation.service
TIMER=openrbi-network-isolation.timer

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"

if [ "$(id -u)" -ne 0 ]; then
    echo "[install-network-isolation-timer] must run as root (it writes to $UNIT_DIR and runs systemctl)." >&2
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now "$TIMER" 2>/dev/null || true
    rm -f "$UNIT_DIR/$SERVICE" "$UNIT_DIR/$TIMER"
    systemctl daemon-reload
    echo "[install-network-isolation-timer] removed $SERVICE and $TIMER."
    echo "  The iptables rules and marker stay in place; clear them with: sudo $REPO_DIR/scripts/setup-network-isolation.sh --remove"
    exit 0
fi

if [ ! -f "$REPO_DIR/scripts/setup-network-isolation.sh" ]; then
    echo "[install-network-isolation-timer] $REPO_DIR/scripts/setup-network-isolation.sh not found — run this from inside an OpenRBI checkout." >&2
    exit 1
fi

case "$REPO_DIR" in
    *[[:space:]]*)
        echo "[install-network-isolation-timer] refusing: checkout path '$REPO_DIR' contains whitespace, which systemd's WorkingDirectory= can't take unquoted." >&2
        exit 1
        ;;
esac

# Rewrite only the WorkingDirectory= line; everything else is copied as-is.
sed "s|^WorkingDirectory=.*$|WorkingDirectory=$REPO_DIR|" \
    "$REPO_DIR/scripts/systemd/$SERVICE" > "$UNIT_DIR/$SERVICE"
cp "$REPO_DIR/scripts/systemd/$TIMER" "$UNIT_DIR/$TIMER"
chmod 644 "$UNIT_DIR/$SERVICE" "$UNIT_DIR/$TIMER"

systemctl daemon-reload
systemctl enable --now "$TIMER"

echo "[install-network-isolation-timer] installed with WorkingDirectory=$REPO_DIR; running $SERVICE once to verify..."
# A oneshot service's `systemctl start` blocks until it finishes and exits
# non-zero if it failed — exactly the check a timer on its own never makes.
if ! systemctl start "$SERVICE"; then
    echo >&2
    echo "[install-network-isolation-timer] FAILED: $SERVICE did not complete successfully." >&2
    echo "  The timer is installed, but every run will fail the same way until this is fixed." >&2
    echo "  Inspect: journalctl -u $SERVICE -n 50 --no-pager" >&2
    exit 1
fi

echo "[install-network-isolation-timer] OK — $SERVICE succeeded."
echo "  Check later with:  systemctl status $SERVICE   (a timer showing 'active (waiting)' says nothing about whether its service runs succeed)"
echo "                     systemctl --failed"
