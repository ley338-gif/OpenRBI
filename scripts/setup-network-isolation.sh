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
MODE="${1:-apply}"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
# The settings below are the same ones docker compose reads from this
# checkout's .env (docker-compose.yml/docker-compose.node.yml), so the
# script reads them from there too: deploy.sh, the systemd unit and a
# manual `sudo ./scripts/setup-network-isolation.sh` then all agree with
# what `docker compose up` actually configured. An explicitly exported
# variable still wins, which the acceptance runners rely on.
ENV_FILE="${OPENRBI_ENV_FILE:-$REPO_DIR/.env}"

# Prints KEY's value from $ENV_FILE (last assignment wins, as in docker
# compose; surrounding quotes and an unquoted trailing " # comment" are
# removed). The file is never sourced: it holds every secret of the
# deployment and this script runs as root.
env_file_value() {
    [ -f "$ENV_FILE" ] || return 0
    raw=$(sed -n "s/^[[:space:]]*\(export[[:space:]][[:space:]]*\)\{0,1\}$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1 | tr -d '\r')
    case "$raw" in
        \"*) raw=${raw#\"}; raw=${raw%%\"*} ;;
        \'*) raw=${raw#\'}; raw=${raw%%\'*} ;;
        *) raw=$(printf '%s' "$raw" | sed 's/[[:space:]]#.*$//') ;;
    esac
    printf '%s' "$raw" | sed 's/[[:space:]]*$//'
}

# setting KEY DEFAULT — the exported environment first, then $ENV_FILE,
# then DEFAULT.
setting() {
    eval "value=\${$1:-}"
    [ -n "$value" ] || value=$(env_file_value "$1")
    [ -n "$value" ] || value="$2"
    printf '%s' "$value"
}

# Compose names the network <project>_browser-plane, the project being
# COMPOSE_PROJECT_NAME or, by default, the checkout directory's name
# (lower-cased, reduced to the characters compose allows).
COMPOSE_PROJECT=$(setting COMPOSE_PROJECT_NAME "$(basename "$REPO_DIR")" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')
BROWSER_PLANE_NETWORK=$(setting OPENRBI_BROWSER_PLANE_NETWORK "${COMPOSE_PROJECT}_browser-plane")
# RBI-POST-002: a plain, self-attested marker file the backend can read
# without any host privilege (bind-mounted read-only, docker-compose.yml)
# to tell "isolation was verifiably applied, recently" apart from "docker
# compose up alone, nobody ran this script" or "ran once, long ago, and
# never reconfirmed since" (e.g. after a host reboot with no timer unit
# installed — see docs/deployment.md and scripts/systemd/). This is a
# presence/freshness signal, not a live re-read of the kernel's netfilter
# tables — the backend container has no host/root access to do that
# itself, by design (docs/adr/0005-no-docker-socket-in-backend.md's same
# minimal-privilege reasoning extends here).
MARKER_DIR="${OPENRBI_NETWORK_ISOLATION_MARKER_DIR:-/var/lib/openrbi/network-isolation}"
MARKER_FILE="$MARKER_DIR/marker"
# Address(es) on browser-plane allowed to *initiate* connections into it.
# Roadmap B2.4 (docs/adr/0024-cross-host-display-relay.md) moved the
# noVNC/VNC relay connection from the backend to each node's own Session
# Agent — it's the only process that still needs to open a *new* connection
# into browser-plane, and the only one this script exempts. Every address
# listed (space-separated) must belong to a session-agent container on this
# host's browser-plane (verify_agent_addresses below); normally that is
# exactly one, the same value docker compose assigns from .env.
#
# Renamed from OPENRBI_BACKEND_BROWSER_PLANE_IP as of Roadmap B2.4 — this is
# a deliberate breaking rename, not a silent repoint: the backend no longer
# has any browser-plane presence to exempt at all, so continuing to honor
# the old variable name would let an operator's existing override silently
# stop applying to anything (see docs/adr/0024's Consequences). Default
# covers Compact's single "session-agent" service (172.30.0.2, the same
# numeric address the backend used to hold) — an un-overridden single-node
# deployment needs no operator action on upgrade. A multi-node deployment
# (Roadmap B2.6) runs this script once per host, each exempting only that
# host's own local agent address.
AGENT_BROWSER_PLANE_IP=$(setting OPENRBI_AGENT_BROWSER_PLANE_IP 172.30.0.2)

log() { echo "[setup-network-isolation] $*"; }

# Refuses (returns 1) unless every exempted address belongs to a
# session-agent container on $BROWSER_PLANE_NETWORK. An exempted address
# that a sandbox holds would give that sandbox an unrestricted ACCEPT into
# the control plane; one nobody holds could be handed to the next sandbox.
# Only when no session agent is attached at all (e.g. the boot-time timer
# running before the containers are up) does it proceed with a warning.
verify_agent_addresses() {
    for ip in $AGENT_BROWSER_PLANE_IP; do
        if ! printf '%s\n' "$ip" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
            echo "OPENRBI_AGENT_BROWSER_PLANE_IP: '$ip' is not an IPv4 address" >&2
            return 1
        fi
    done
    if ! members=$(docker network inspect "$BROWSER_PLANE_NETWORK" \
        --format '{{range $id, $c := .Containers}}{{$id}} {{$c.IPv4Address}}{{"\n"}}{{end}}' 2>/dev/null); then
        echo "docker network '$BROWSER_PLANE_NETWORK' not found — set OPENRBI_BROWSER_PLANE_NETWORK or COMPOSE_PROJECT_NAME (in the environment or $ENV_FILE)" >&2
        return 1
    fi
    agent_ips=""
    for id in $(printf '%s\n' "$members" | awk 'NF {print $1}'); do
        service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id" 2>/dev/null || true)
        if [ "$service" = "session-agent" ]; then
            agent_ips="$agent_ips $(printf '%s\n' "$members" | awk -v id="$id" '$1 == id {split($2, a, "/"); print a[1]}')"
        fi
    done
    if [ -z "$agent_ips" ]; then
        log "warning: no session-agent container is attached to $BROWSER_PLANE_NETWORK yet — exempting $AGENT_BROWSER_PLANE_IP as configured"
        return 0
    fi
    for ip in $AGENT_BROWSER_PLANE_IP; do
        case " $agent_ips " in
            *" $ip "*) ;;
            *)
                holder=$(printf '%s\n' "$members" | awk -v ip="$ip" '{split($2, a, "/"); if (a[1] == ip) print $1}')
                if [ -n "$holder" ]; then
                    what="it belongs to $(docker inspect --format '{{.Name}}' "$holder" | sed 's#^/##'), not to the session agent"
                else
                    what="no container holds it, so the next sandbox could be given it"
                fi
                echo "refusing to exempt $ip on $BROWSER_PLANE_NETWORK: $what. The session agent's address is:$agent_ips — set OPENRBI_AGENT_BROWSER_PLANE_IP to match (in the environment or $ENV_FILE). No iptables rule was changed." >&2
                return 1
                ;;
        esac
    done
    for ip in $agent_ips; do
        case " $AGENT_BROWSER_PLANE_IP " in
            *" $ip "*) ;;
            *)
                echo "refusing to apply: the session agent on $BROWSER_PLANE_NETWORK has address $ip, which OPENRBI_AGENT_BROWSER_PLANE_IP ($AGENT_BROWSER_PLANE_IP) does not exempt — its display relay would be blocked. No iptables rule was changed." >&2
                return 1
                ;;
        esac
    done
}

case "$MODE" in
    apply|--remove|--check) ;;
    *)
        echo "usage: $0 [--remove|--check]" >&2
        exit 1
        ;;
esac

log "browser-plane network: $BROWSER_PLANE_NETWORK, exempted session-agent address: $AGENT_BROWSER_PLANE_IP"

# --check: validate the resolved settings against the running containers
# without touching iptables (no root needed).
if [ "$MODE" = "--check" ]; then
    verify_agent_addresses
    log "check passed"
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "must run as root (iptables/ip require it)" >&2
    exit 1
fi

# Validate before the old rules are removed below: a refused run leaves the
# previous rules in place and the marker un-refreshed, so the health check
# turns DEGRADED instead of the host silently running a wrong exemption.
if [ "$MODE" = "apply" ]; then
    verify_agent_addresses
fi

# --- Remove any rules we previously added (idempotent re-run). Deleting by
# line number from the bottom up avoids renumbering issues as rules shift. ---
while true; do
    RULE_NUM=$(iptables -L DOCKER-USER -n --line-numbers 2>/dev/null | grep -- "$MARKER" | tail -1 | awk '{print $1}')
    [ -z "$RULE_NUM" ] && break
    iptables -D DOCKER-USER "$RULE_NUM"
done
log "cleared any previous $MARKER rules"

if [ "$MODE" = "--remove" ]; then
    rm -f "$MARKER_FILE"
    log "remove-only mode complete (marker file cleared — network_isolation health will report NOT_CONFIGURED)"
    exit 0
fi

BROWSER_SUBNET=$(docker network inspect "$BROWSER_PLANE_NETWORK" --format '{{(index .IPAM.Config 0).Subnet}}')
if [ -z "$BROWSER_SUBNET" ]; then
    echo "could not determine subnet for network $BROWSER_PLANE_NETWORK" >&2
    exit 1
fi
log "browser-plane subnet: $BROWSER_SUBNET"

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
# session agent's own outbound connection to a sandbox's VNC port, Roadmap
# B2.4) before the rules above would otherwise catch it — conntrack state,
# not a blanket hole: sandboxes still cannot open NEW connections into the
# control plane. ---
iptables -I DOCKER-USER 1 -s "$BROWSER_SUBNET" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT -m comment --comment "$MARKER"

# --- Exactly the address(es) that own the display relay must additionally
# be allowed to open NEW connections into browser-plane (that's the whole
# point of the relay) — placed last so each ends up topmost, ahead of every
# DROP rule above, including the peer-isolation rule that would otherwise
# catch it too (it shares the same subnet as real sandboxes). No other
# address gets this. ---
for ip in $AGENT_BROWSER_PLANE_IP; do
    iptables -I DOCKER-USER 1 -s "$ip" -j ACCEPT -m comment --comment "$MARKER"
done

mkdir -p "$MARKER_DIR"
{
    echo "MARKER=$MARKER"
    echo "APPLIED_AT=$(date +%s)"
    echo "BROWSER_PLANE_SUBNET=$BROWSER_SUBNET"
} > "$MARKER_FILE"
chmod 644 "$MARKER_FILE"
log "wrote marker file: $MARKER_FILE"

log "done. Verify with: iptables -L DOCKER-USER -n --line-numbers"
log "re-run this script after every host reboot and after any Docker/network"
log "recreation — install scripts/systemd/openrbi-network-isolation.{service,timer}"
log "to automate that instead of relying on someone remembering (see"
log "docs/deployment.md#network-isolation)."
