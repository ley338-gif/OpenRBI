# Hardened Firefox browser sandbox image (docs/adr/0006, docs/security-model.md#sandbox-model).
#
# Runtime hardening (non-root, dropped capabilities, no-new-privileges,
# read-only rootfs, resource limits) is applied by the SandboxProvider at
# container-create time (session-agent/app/providers/docker_provider.py),
# not baked into this image — this Dockerfile only needs to make sure
# everything it does at runtime actually works under those constraints
# (e.g. all writes go to the tmpfs-mounted /tmp, never to the image's own
# read-only filesystem).
FROM debian:bookworm-slim

ARG OPENRBI_VERSION=0.1.1
ARG OPENRBI_COMMIT_SHA=unknown
ARG OPENRBI_BUILD_DATE=unknown
LABEL org.opencontainers.image.title="OpenRBI Browser Sandbox" \
      org.opencontainers.image.version="$OPENRBI_VERSION" \
      org.opencontainers.image.revision="$OPENRBI_COMMIT_SHA" \
      org.opencontainers.image.created="$OPENRBI_BUILD_DATE"
ENV OPENRBI_VERSION="$OPENRBI_VERSION" \
    OPENRBI_COMMIT_SHA="$OPENRBI_COMMIT_SHA" \
    OPENRBI_BUILD_DATE="$OPENRBI_BUILD_DATE"

ENV DEBIAN_FRONTEND=noninteractive

# upgrade before install so firefox-esr's own dependency chain (glib,
# sqlite3, libxml2, ...) resolves against whatever OS security patches
# Debian has actually released, not just what apt's default resolver would
# otherwise pick (A5).
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        firefox-esr \
        xvfb \
        x11vnc \
        dbus-x11 \
        fonts-liberation \
        ca-certificates \
        attr \
    && rm -rf /var/lib/apt/lists/*

# Fixed non-root uid:gid — matches the "10001:10001" user set by
# DockerSandboxProvider._create_session_sync (kept here too so the image
# also works correctly if run directly, e.g. for local testing).
RUN groupadd -g 10001 openrbi \
    && useradd -u 10001 -g openrbi -M -d /tmp/home -s /usr/sbin/nologin openrbi

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER openrbi
ENV HOME=/tmp/home
ENV DISPLAY=:99
# Container-level isolation (ADR 0010) is this platform's primary sandbox
# boundary; Firefox's own content-process sandbox additionally wants
# capabilities (e.g. unprivileged user namespaces) that conflict with
# cap_drop=ALL + no-new-privileges. Disabling it here avoids Firefox
# silently failing to start under those constraints — documented, not a
# silent security downgrade, since the container boundary is unaffected.
ENV MOZ_DISABLE_CONTENT_SANDBOX=1

# Not published to the host or any public network by the SandboxProvider;
# reachable only from whatever network the session's container is attached
# to (Phase 8 wires up the actual noVNC connection path).
EXPOSE 5900

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
