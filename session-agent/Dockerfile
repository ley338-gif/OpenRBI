# NOTE: This is the only OpenRBI component that legitimately needs access to
# the container-runtime socket. It must never share a network namespace or
# credentials with the backend/frontend, and must never be reachable from
# inside a browser sandbox (see docs/adr/0004, 0005).
FROM python:3.11-slim AS base

# Pulls in whatever OS security patches Debian has actually released for
# this base image since it was last pulled (A5) — some CVEs still show up
# afterward with no upstream fix yet, tracked explicitly in .trivyignore.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app

# Non-root, but in group 0: the bind-mounted docker.sock is typically
# root:root/root:docker with group read-write (see docs/deployment.md) —
# putting the app user in group 0 grants socket access without making the
# process itself uid 0. This does not fully neutralize a container escape
# (group 0 is still broadly privileged on many hosts) but does drop the
# process out of "actually root", which is the achievable improvement here
# without depending on a host-specific docker-group GID (Phase 20 hardening).
RUN useradd --create-home --uid 10001 --gid 0 openrbi
USER openrbi

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
