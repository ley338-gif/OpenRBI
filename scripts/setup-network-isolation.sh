#!/bin/sh
# Applies the browser-sandbox network egress blocklist (docs/security-model.md
# #network-isolation, project brief §10) to the Docker host's DOCKER-USER
# iptables chain. Run once after `docker compose up` on the actual deployment
# host (requires root and the `iptables`, `ip`, `docker` binaries — this is a
# Linux-server-only script per docs/deployment.md's stated requirements).
#
# Idempotent: every rule this script adds is tagged with a comment
# containing $MARKER, and existing tagged rules are removed before new ones
# are added, so re-running after a config change (e.g. a new docker network
# appearing) is safe and doesn't accumulate duplicate rules.
#
# What this does NOT do (tracked gaps, see docs/security-model.md):
#   - No fine-grained DNS-response validation / dedicated resolver. The
#     blocklist below matches on destination IP regardless of how it was
#     obtained, which already defeats DNS rebinding for connection-level
#     access (a resolved-then-dialed blocked address is dropped exactly the
#     same as a hardcoded one) — but it doesn't proactively reject a DNS
#     *answer* before a connection attempt, and it doesn't yet emit a
#     SecurityEvent (NETWORK_ACCESS_BLOCKED) automatically; blocked attempts
#     are only visible via the kernel log (LOG target below) until a log
#     shipper is built.
#   - IPv6 is not selectively filtered — it is disabled outright on the
#     browser-plane network (docker-compose.yml, enable_ipv6: false), which
#     is a strictly more restrictive outcome than allow-listing.
set -eu

MARKER="openrbi-network-isolation"
BROWSER_PLANE_NETWORK="${OPENRBI_BROWSER_PLANE_NETWORK:-openrbi_browser-plane}"
# Backend's pinned address on browser-plane (docker-compose.yml) — the one
# address in this subnet allowed to *initiate* connections into it, since
# it's indistinguishable from a real sandbox by subnet alone otherwise.
BACKEND_BROWSER_PLANE_IP="${OPENRBI_BACKEND_BROWSER_PLANE_IP:-172.30.0.2}"

log() { echo "[setup-network-isolation] $*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "must run as root (iptables/ip require it)" >&2
    exit 1
fi

BROWSER_SUBNET=$(docker network inspect "$BROWSER_PLANE_NETWORK" --format '{{(index .IPAM.Config 0).Subnet}}')
if [ -z "$BROWSER_SUBNET" ]; then
    echo "could not determine subnet for network $BROWSER_PLANE_NETWORK" >&2
    exit 1
fi
log "browser-plane subnet: $BROWSER_SUBNET"

# --- Remove any rules we previously added (idempotent re-run). Deleting by
# line number from the bottom up avoids renumbering issues as rules shift. ---
while true; do
    RULE_NUM=$(iptables -L DOCKER-USER -n --line-numbers 2>/dev/null | grep -- "$MARKER" | tail -1 | awk '{print $1}')
    [ -z "$RULE_NUM" ] && break
    iptables -D DOCKER-USER "$RULE_NUM"
done
log "cleared any previous $MARKER rules"

# Each -I inserts at position 1 (top), so whichever we insert LAST ends up
# evaluated FIRST. LOG must end up on top of its matching DROP — it's a
# non-terminating target, so the packet falls through to DROP right below
# it — otherwise DROP (a terminating target) would intercept the packet
# first and the LOG rule below it would never be reached at all.
insert_drop() {
    dest="$1"
    iptables -I DOCKER-USER 1 -s "$BROWSER_SUBNET" -d "$dest" -j DROP -m comment --comment "$MARKER"
    iptables -I DOCKER-USER 1 -s "$BROWSER_SUBNET" -d "$dest" -j LOG --log-prefix "openrbi-blocked: " --log-level 4 -m comment --comment "$MARKER"
}

# --- Static blocklist (project brief §10, IPv4) ---
for cidr in \
    0.0.0.0/8 \
    10.0.0.0/8 \
    100.64.0.0/10 \
    127.0.0.0/8 \
    169.254.0.0/16 \
    172.16.0.0/12 \
    192.0.0.0/24 \
    192.168.0.0/16 \
    198.18.0.0/15 \
    224.0.0.0/4 \
    240.0.0.0/4 \
; do
    insert_drop "$cidr"
done
log "static IPv4 blocklist applied"

# --- Sandboxes must not reach each other either (session isolation, project
# brief §8: no shared writable state or cross-session access) ---
insert_drop "$BROWSER_SUBNET"
log "sandbox peer-to-peer isolation applied"

# --- Dynamic: every other docker network's subnet (control-plane included;
# this also transparently covers any *other* docker-compose projects on the
# same host) ---
for net in $(docker network ls --format '{{.Name}}'); do
    [ "$net" = "$BROWSER_PLANE_NETWORK" ] && continue
    subnet=$(docker network inspect "$net" --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null || true)
    for s in $subnet; do
        insert_drop "$s"
    done
done
log "dynamic docker-network blocklist applied"

# --- Dynamic: the host's own IP addresses on every real interface ---
for ip in $(ip -4 -o addr show scope global | awk '{print $4}'); do
    insert_drop "$ip"
done
log "dynamic host-IP blocklist applied"

# --- Allow return traffic for control-plane-initiated connections (the
# backend's own outbound connection to a sandbox's VNC port, Phase 8) before
# the rules above would otherwise catch it — conntrack state, not a blanket
# hole: sandboxes still cannot open NEW connections into the control plane. ---
iptables -I DOCKER-USER 1 -s "$BROWSER_SUBNET" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT -m comment --comment "$MARKER"

# --- Backend's own pinned address must additionally be allowed to open NEW
# connections into browser-plane (that's the whole point of the display
# relay) — placed last so it ends up topmost, ahead of every DROP rule
# above, including the peer-isolation rule that would otherwise catch it
# too (it shares the same subnet as real sandboxes). ---
iptables -I DOCKER-USER 1 -s "$BACKEND_BROWSER_PLANE_IP" -j ACCEPT -m comment --comment "$MARKER"

log "done. Verify with: iptables -L DOCKER-USER -n --line-numbers"
