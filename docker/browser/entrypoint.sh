#!/bin/sh
# Every path written here lives under $HOME (/tmp/home, tmpfs) so nothing
# persists past container destruction — see docs/adr/0007 (no persistent
# browser profiles) and docs/security-model.md#data-protection--retention.
set -eu

PROFILE_DIR="$HOME/firefox-profile"
mkdir -p "$PROFILE_DIR"

Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp &
XVFB_PID=$!

i=0
while [ ! -e /tmp/.X11-unix/X99 ] && [ "$i" -lt 40 ]; do
    sleep 0.25
    i=$((i + 1))
done

# No VNC password: this MVP relies on network isolation (no path from the
# public internet or the browser's own egress network to this port) rather
# than VNC's own weak auth. Known limitation, tracked for Phase 8/9/20 —
# see docs/security-model.md.
x11vnc -display "$DISPLAY" -forever -shared -nopw -quiet -rfbport 5900 &
VNC_PID=$!

cleanup() {
    kill "$XVFB_PID" "$VNC_PID" "$FF_PID" 2>/dev/null || true
}
trap cleanup TERM INT

firefox-esr --no-remote --profile "$PROFILE_DIR" --new-instance about:blank &
FF_PID=$!

wait "$FF_PID"
