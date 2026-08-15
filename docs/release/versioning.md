# Versioning and build metadata

OpenRBI uses Semantic Versioning for v1 release tags (`v1.0.0-rc.N`, then `v1.0.0`). The root `VERSION` file is the authoritative source version. Python and Node package manifests keep the same value because their build tools require a local manifest version; `scripts/check-version-sync.py` makes drift a CI failure.

Every shipped image accepts the same build arguments:

- `OPENRBI_VERSION` — release version without the Git tag's leading `v`
- `OPENRBI_COMMIT_SHA` — full Git commit SHA
- `OPENRBI_BUILD_DATE` — UTC RFC 3339 build timestamp

The values are stored as standard OCI image labels (`org.opencontainers.image.version`, `revision`, and `created`). Backend and Session Agent also expose them from their unauthenticated `/health` liveness response and use the release version in their OpenAPI metadata. The static frontend image publishes `/version.json`. The browser image carries the values as OCI labels and environment metadata for container inspection.

Local builds use the manifest version and `unknown` for commit/date. Release builds must pass all three values explicitly; the release workflow records image digests separately.

## Version update procedure

1. Update `VERSION` and every package/image default reported by `python scripts/check-version-sync.py`.
2. Update `CHANGELOG.md` for the release.
3. Run the version check, release gates, and acceptance suite.
4. Tag the exact green `main` commit as `v<version>`.

Do not infer a deployed version from `latest`, a branch name, or a mutable base-image tag.
