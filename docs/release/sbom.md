# Software Bills of Materials

Every release workflow build generates one CycloneDX JSON Software Bill of
Materials (SBOM) for each shipped image:

- `backend.cdx.json`
- `session-agent.cdx.json`
- `frontend.cdx.json`
- `browser.cdx.json`

The workflow uses Syft 1.51.0 installed through the Anchore action pinned to an
immutable commit. SBOM generation scans the locally built
image during a dry run and the digest-addressed registry image during an actual
publication. A malformed result or a result that is not CycloneDX JSON fails the
workflow.

Each image metadata record links its SBOM filename and specification version to
the same image reference and content identity. `release-metadata.json` records
the version, source commit, UTC build time, and all four image identities.
`SHA256SUMS` covers the aggregate manifest, per-image metadata, and every SBOM.

Dry-run SBOMs are downloadable workflow artifacts retained for 90 days. During
publication the same files become GitHub Release assets. The registry manifest
digest is authoritative for a published image; a dry run records a local image
ID because it deliberately pushes nothing.

Image signing and Cosign attestations are intentionally deferred beyond the
v1.0 blocker set. SBOMs improve inventory and incident response, but do not by
themselves prove image authenticity or absence of vulnerabilities.
