# Release publishing

The manually dispatched GitHub Actions workflow `.github/workflows/release.yml`
builds all four OpenRBI images from one exact commit. It supports Semantic
Versioning tags, including candidates such as `v1.0.1-rc.N` and GA tags such as `v1.0.1`. The requested tag must
match the root `VERSION` value exactly (apart from the leading `v`).

## Safety gates

The workflow fails unless all of these conditions hold:

1. It was dispatched from `main` and the selected commit is present on `main`.
2. That exact commit has a successful required `Release gates` check.
3. The tag is a supported version and agrees with every component through the
   normal version-sync gate.
4. For publishing, the tag must not exist and repository variable
   `OPENRBI_RELEASES_ENABLED` must equal `true`.

The final switch is deliberately absent/false during workflow development.
Do not enable it until a dry run for the intended release commit succeeds.

## Dry run

Dispatch **Release** on `main`, leave `version` empty (or enter `v<VERSION>`),
and leave `publish` disabled. The workflow builds every Linux/amd64 image but
does not push, tag, or create a GitHub Release. It uploads a 90-day manifest
artifact containing version, commit SHA, UTC build date, exact image references,
and content-addressed local image IDs. It also contains all four CycloneDX SBOMs
and a `SHA256SUMS` file. This is the required first validation.

## Publishing an RC or stable release

After the source version and changelog have been updated and all acceptance
work is complete:

1. Confirm a dry run succeeded for the exact `main` commit.
2. Set repository variable `OPENRBI_RELEASES_ENABLED=true`.
3. Dispatch the workflow from that commit with `publish` enabled.
4. Verify the four immutable version tags, registry manifest digests, CycloneDX
   SBOMs, and `SHA256SUMS` in the generated manifest and GitHub Release assets.
5. Set `OPENRBI_RELEASES_ENABLED=false` again after publication.

Published image names are:

- `ghcr.io/<owner>/openrbi-backend:<version>`
- `ghcr.io/<owner>/openrbi-session-agent:<version>`
- `ghcr.io/<owner>/openrbi-frontend:<version>`
- `ghcr.io/<owner>/openrbi-browser:<version>`

The workflow intentionally does not publish `latest`; consumers must select an
explicit version. RC tags create prerelease GitHub Releases. A stable v1 tag
creates a normal GitHub Release. Every image embeds the same version, full
commit SHA, and build date as OCI provenance labels.

SBOM format, validation, and limitations are documented in
[`sbom.md`](sbom.md).
