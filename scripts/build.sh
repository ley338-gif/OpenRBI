#!/bin/sh
# RBI-POST-014: a plain `docker compose build` passes no OPENRBI_VERSION/
# OPENRBI_COMMIT_SHA/OPENRBI_BUILD_DATE build args, so every image built
# this way silently falls back to each Dockerfile's ARG defaults
# (OPENRBI_VERSION=1.0.0, OPENRBI_COMMIT_SHA=unknown,
# OPENRBI_BUILD_DATE=unknown) — a locally-built image reports the same
# version number release-after-release and no real commit/date at all,
# useless for "which exact code is this admin looking at" during support
# or an incident. .github/workflows/release.yml already sets these
# correctly for an official release build (git tag, $GITHUB_SHA, a real
# UTC timestamp) — this script gives local/development builds the same
# real values, computed from git instead of hardcoded.
#
# Usage: ./scripts/build.sh [any extra `docker compose build` args]
#   ./scripts/build.sh                  # build every service
#   ./scripts/build.sh backend          # build just one service
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "not a git checkout — can't determine VERSION/COMMIT_SHA; falling back to Dockerfile defaults" >&2
    exec docker compose build "$@"
fi

# --tags --always: the exact release tag on a tagged commit (e.g.
# "v1.0.1"), or "<tag>-<N>-g<sha>" / a bare short SHA if there's no tag
# reachable yet — always something more informative than the Dockerfile's
# static "1.0.0" default, never a failure just because no tag exists yet.
VERSION="$(git describe --tags --always --dirty 2>/dev/null || echo unknown)"
COMMIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

echo "[build] local development build — not an official release artifact"
echo "[build] OPENRBI_VERSION=$VERSION"
echo "[build] OPENRBI_COMMIT_SHA=$COMMIT_SHA"
echo "[build] OPENRBI_BUILD_DATE=$BUILD_DATE"

export OPENRBI_VERSION="$VERSION"
export OPENRBI_COMMIT_SHA="$COMMIT_SHA"
export OPENRBI_BUILD_DATE="$BUILD_DATE"

# docker-compose.yml's build: sections don't declare `args:` (deliberately
# — see docker-compose.yml's own comment once this lands), so
# docker-compose-file-level variable substitution won't reach these into
# the build automatically. Pass them explicitly per service via
# --build-arg instead, which works regardless of the compose file.
exec docker compose build \
    --build-arg "OPENRBI_VERSION=$VERSION" \
    --build-arg "OPENRBI_COMMIT_SHA=$COMMIT_SHA" \
    --build-arg "OPENRBI_BUILD_DATE=$BUILD_DATE" \
    "$@"
