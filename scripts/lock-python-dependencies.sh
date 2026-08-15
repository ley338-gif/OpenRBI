#!/bin/sh
# Regenerate the exact, hash-verified dependency sets used by CI and images.
# The target matches OpenRBI's supported v1 production platform.
set -eu

UV_VERSION="0.8.13"
TARGET_PLATFORM="x86_64-manylinux_2_17"
TARGET_PYTHON="3.11"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv ${UV_VERSION} is required (python -m pip install uv==${UV_VERSION})" >&2
    exit 1
fi

ACTUAL_UV_VERSION="$(uv --version | awk '{print $2}')"
if [ "$ACTUAL_UV_VERSION" != "$UV_VERSION" ]; then
    echo "uv ${UV_VERSION} is required; found ${ACTUAL_UV_VERSION}" >&2
    exit 1
fi

compile_lock() {
    component="$1"
    output="$2"
    shift 2
    uv pip compile "$REPO_ROOT/$component/pyproject.toml" \
        "$@" \
        --python-platform "$TARGET_PLATFORM" \
        --python-version "$TARGET_PYTHON" \
        --generate-hashes \
        --custom-compile-command "scripts/lock-python-dependencies.sh" \
        --output-file "$REPO_ROOT/$component/$output"
}

compile_lock backend requirements.lock
compile_lock backend requirements-dev.lock --extra dev
compile_lock session-agent requirements.lock
compile_lock session-agent requirements-dev.lock --extra dev
