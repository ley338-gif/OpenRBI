#!/bin/sh
# Builds the hardened browser sandbox image (docker/browser/). Not a
# docker-compose service: the Session Agent spawns per-session containers
# from this image directly via the Docker API, it isn't a long-running
# compose service itself.
#
# --pull --no-cache: Firefox ESR comes from Debian's security repo via the
# Dockerfile's `apt-get upgrade && apt-get install`. That RUN line never
# changes, so a cached build silently keeps whatever Firefox was current
# the first time it ran — a rebuild would report success and ship the old,
# vulnerable browser. Always re-resolve the base image and the packages.
set -eu
cd "$(dirname "$0")/.."
docker build --pull --no-cache -t openrbi-browser:latest docker/browser
