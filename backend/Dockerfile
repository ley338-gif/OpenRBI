FROM python:3.11-slim AS base

ARG OPENRBI_VERSION=0.1.1
ARG OPENRBI_COMMIT_SHA=unknown
ARG OPENRBI_BUILD_DATE=unknown
LABEL org.opencontainers.image.title="OpenRBI Backend" \
      org.opencontainers.image.version="$OPENRBI_VERSION" \
      org.opencontainers.image.revision="$OPENRBI_COMMIT_SHA" \
      org.opencontainers.image.created="$OPENRBI_BUILD_DATE"
ENV OPENRBI_VERSION="$OPENRBI_VERSION" \
    OPENRBI_COMMIT_SHA="$OPENRBI_COMMIT_SHA" \
    OPENRBI_BUILD_DATE="$OPENRBI_BUILD_DATE"

# libmagic1: backing library for python-magic (real magic-byte file-type
# detection, Phase 13 download interception — never trust extension or
# declared Content-Type alone, docs/policies.md).
# libldap2/libsasl2-2: runtime shared libs python-ldap's compiled extension
# needs to actually load (Roadmap Phase B / B1.2) — installed by name
# explicitly so they're marked "manually installed" and survive the
# --auto-remove purge below, which only targets the build-time-only
# compiler/headers.
# Pulls in whatever OS security patches Debian has actually released for
# this base image since it was last pulled — some upstream CVEs still show
# up as unfixed afterward (Debian hasn't backported a patch yet), tracked
# explicitly in .trivyignore rather than silently accepted (A5).
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libmagic1 libldap2 libsasl2-2 \
    && apt-get install -y --no-install-recommends gcc libldap-dev libsasl2-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 openrbi
WORKDIR /app

COPY pyproject.toml ./
# python-ldap's C extension only needs gcc/libldap2-dev/libsasl2-dev to
# *compile* against — purging them right after this one RUN keeps them out
# of the final image layers entirely (single RUN, not a separate step, so
# they never persist in the image history).
RUN pip install --no-cache-dir . \
    && apt-get purge -y --auto-remove gcc libldap-dev libsasl2-dev python3-dev

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN mkdir -p /app/data/staging && chown -R openrbi:openrbi /app/data

USER openrbi
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
