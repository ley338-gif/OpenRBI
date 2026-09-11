#!/bin/sh
# Builds the hardened browser sandbox image (docker/browser/). Not a
# docker-compose service: the Session Agent spawns per-session containers
# from this image directly via the Docker API, it isn't a long-running
# compose service itself.
set -eu
cd "$(dirname "$0")/.."
docker build -t openrbi-browser:latest docker/browser
