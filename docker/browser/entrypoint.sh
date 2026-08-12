#!/bin/sh
# Every path written here lives under $HOME (/tmp/home, tmpfs) so nothing
# persists past container destruction — see docs/adr/0007 (no persistent
# browser profiles) and docs/security-model.md#data-protection--retention.
set -eu

PROFILE_DIR="$HOME/firefox-profile"
DOWNLOAD_DIR="$HOME/downloads"
mkdir -p "$PROFILE_DIR" "$DOWNLOAD_DIR"

# Silent auto-download to a fixed, known directory — Phase 13's download
# interception polls exactly this path via the Session Agent's Docker API
# access (docs/quarantine.md). No per-file save-as prompt: an isolated
# browser session has nowhere sensible to show that dialog anyway, and the
# real gate is the policy engine downstream, not a client-side prompt.
cat > "$PROFILE_DIR/user.js" <<EOF
user_pref("browser.download.folderList", 2);
user_pref("browser.download.dir", "$DOWNLOAD_DIR");
user_pref("browser.download.useDownloadDir", true);
user_pref("browser.download.always_ask_before_handling_new_types", false);
user_pref("browser.helperApps.neverAsk.saveToDisk", "application/octet-stream,application/pdf,application/zip,application/x-msdownload,application/x-msdos-program,application/vnd.microsoft.portable-executable,text/plain,application/x-sh");
user_pref("browser.download.manager.showWhenStarting", false);
EOF

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
