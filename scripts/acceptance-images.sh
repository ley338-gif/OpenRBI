# shellcheck shell=sh
# Sourced by the acceptance runners. docs/release/release-process.md step 6
# requires the v1 acceptance suite to run against the *published* RC images,
# not locally rebuilt substitutes. Every runner builds from source by default;
# with OPENRBI_ACCEPTANCE_IMAGES pointing at a directory holding a release's
# <component>.metadata.json files (GitHub Release assets), it instead pulls
# each published image by its recorded registry digest, checks the image's
# OCI version/revision labels against that metadata, and tags it with the
# local name the runner would otherwise have built. Compose then finds the
# image locally and never builds.

acceptance_images_enabled() {
    [ -n "${OPENRBI_ACCEPTANCE_IMAGES:-}" ]
}

# use_published_image <component> <local image tag>
use_published_image() {
    meta="$OPENRBI_ACCEPTANCE_IMAGES/$1.metadata.json"
    [ -f "$meta" ] || { echo "[acceptance-images] missing release metadata: $meta" >&2; return 1; }
    command -v jq >/dev/null 2>&1 || { echo "[acceptance-images] jq is required" >&2; return 1; }
    jq -e '.published == true and .digest_kind == "registry_manifest_digest"' "$meta" >/dev/null \
        || { echo "[acceptance-images] $meta does not describe a published registry image" >&2; return 1; }
    ref="$(jq -er '.image | sub(":[^:/]+$"; "")' "$meta")@$(jq -er '.digest' "$meta")"
    want_version="$(jq -er '.version' "$meta")"
    want_revision="$(jq -er '.commit_sha' "$meta")"
    docker pull --quiet "$ref" >/dev/null
    got_version="$(docker image inspect "$ref" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')"
    got_revision="$(docker image inspect "$ref" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
    if [ "$got_version" != "$want_version" ] || [ "$got_revision" != "$want_revision" ]; then
        echo "[acceptance-images] $ref labels ($got_version, $got_revision) do not match its release metadata ($want_version, $want_revision)" >&2
        return 1
    fi
    docker tag "$ref" "$2"
    echo "[acceptance-images] $2 <- $ref ($want_version, $want_revision)"
}

# use_published_images <compose project name>
use_published_images() {
    use_published_image backend "$1-backend:latest"
    use_published_image session-agent "$1-session-agent:latest"
    use_published_image frontend "$1-frontend:latest"
    use_published_image browser openrbi-browser:latest
}
