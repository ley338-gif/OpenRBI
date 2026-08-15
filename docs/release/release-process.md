# Release process

This runbook governs OpenRBI release candidates (`vX.Y.Z-rc.N`) and GA releases (`vX.Y.Z`). It complements the mechanical
publishing details in [`publishing.md`](publishing.md); neither document permits
bypassing a failing gate.

## Entry criteria

The exact candidate commit must be on `main` and satisfy all of the following:

- P0 defects: zero.
- Known P1 release blockers: zero.
- Its own required `Release gates` check is successful.
- Security, LDAP, fault injection, clean installation, backup/restore and
  upgrade jobs are green.
- [`v1-acceptance.md`](v1-acceptance.md) records all 35 scenarios as PASS.
- The documentation freeze review is complete and no known contradiction
  between implementation, tests and documentation remains.

## RC sequence

1. Select the already-green `main` commit. Do not add changes after selection.
2. Update the authoritative root `VERSION` to the intended release candidate (for example `1.0.1-rc.1`) and synchronize all
   component manifests/defaults as described in [`versioning.md`](versioning.md).
3. Merge that version-only change through a PR and wait for the new commit's
   full release gates. Earlier green runs do not transfer to the version commit.
4. Run the release workflow in dry-run mode. Verify all four images, metadata,
   CycloneDX SBOMs, checksums and provenance before enabling publication.
5. If publication is authorized, dispatch the same workflow for the exact
   green commit with `OPENRBI_RELEASES_ENABLED=true`. Confirm GHCR manifest
   digests and the GitHub prerelease assets match the dry run.
6. Execute the complete v1 acceptance suite against the published RC artifacts,
   not locally rebuilt substitutes. Record any deviation as a defect.
7. Accept only release-blocking bug fixes. A fix requires `rc.2` (or later), a
   new full gate run, dry run and complete acceptance repetition.
8. Promote to GA only from a green accepted RC tree, through the same
   version PR, gates, dry run, artifact verification and publication controls.

## Stop conditions

Stop immediately for a failing/absent required check, unresolved P0/P1,
unreviewed migration, missing artifact/digest/SBOM, acceptance mismatch,
documentation contradiction, or a tag target that differs from the accepted
commit. Do not rerun until the failure is understood and fixed; never weaken a
gate to make a release pass.

## Post-publication verification

- Confirm the tag and GitHub Release target the accepted `main` commit.
- Pull every published image by recorded digest and verify its OCI labels.
- Verify `SHA256SUMS` and each CycloneDX SBOM download.
- Perform clean-install and supported upgrade smoke checks from published
  images, then retain their logs with the release record.
- Announce known limitations from `docs/supported-configurations.md` and the
  security review; do not market technology previews as supported.
