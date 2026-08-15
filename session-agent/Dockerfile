# NOTE: This is the only OpenRBI component that legitimately needs access to
# the container-runtime socket. It must never share a network namespace or
# credentials with the backend/frontend, and must never be reachable from
# inside a browser sandbox (see docs/adr/0004, 0005).
FROM python:3.11-slim AS base

ARG OPENRBI_VERSION=1.0.1
ARG OPENRBI_COMMIT_SHA=unknown
ARG OPENRBI_BUILD_DATE=unknown
LABEL org.opencontainers.image.title="OpenRBI Session Agent" \
      org.opencontainers.image.version="$OPENRBI_VERSION" \
      org.opencontainers.image.revision="$OPENRBI_COMMIT_SHA" \
      org.opencontainers.image.created="$OPENRBI_BUILD_DATE"
ENV OPENRBI_VERSION="$OPENRBI_VERSION" \
    OPENRBI_COMMIT_SHA="$OPENRBI_COMMIT_SHA" \
    OPENRBI_BUILD_DATE="$OPENRBI_BUILD_DATE"

# Pulls in whatever OS security patches Debian has actually released for
# this base image since it was last pulled (A5) — some CVEs still show up
# afterward with no upstream fix yet, tracked explicitly in .trivyignore.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.lock requirements-dev.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app

# Non-root: primary group 0 drops the process out of "actually uid 0"
# without granting it anything docker.sock needs on its own — that
# access comes from docker-compose.yml's group_add, which supplies the
# real host docker-group GID as a *supplementary* group at container
# start time (found empirically to be required: docker.sock is normally
# root:<docker-group> mode 660 on a real host, and that group's GID is
# essentially never 0, so primary-group-0 alone does not grant access —
# see docker-compose.yml's session-agent service for the actual fix and
# docs/deployment.md#installation for the required host-side step).
RUN useradd --create-home --uid 10001 --gid 0 openrbi
USER openrbi

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
