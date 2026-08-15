# Repository protection — release tags

RBI-POST-004 (v1.0.1 hardening sprint). `.github/workflows/release.yml` already refuses to publish a release for a tag that already exists on the remote (application-level guard, not a GitHub setting) — but nothing at the GitHub-settings level stopped a user with direct push access from deleting or force-repointing an already-published `v*` tag afterward. Once a release is out, its tag should be immutable: it's the thing SBOMs, image digests, and `docs/release/*.md` evidence files all point back to.

## Configuration applied

A repository ruleset, created via the GitHub API (`POST /repos/ley338-gif/OpenRBI/rulesets`) and verified via `GET /repos/ley338-gif/OpenRBI/rulesets/20885204`:

| Field | Value |
|---|---|
| Name | `protect-release-tags` |
| Target | `tag` |
| Enforcement | `active` |
| Ref pattern | `refs/tags/v*` (include), no exclusions |
| Rules | `deletion` (blocks `git push --delete` / deleting the tag), `non_fast_forward` (blocks force-repointing an existing tag to a different commit) |
| Bypass actors | none — `current_user_can_bypass: "never"` |

Effect: `git push --delete origin v1.0.0` or `git push --force origin v1.0.0` (or the equivalent from the GitHub UI/API) is rejected by GitHub itself, for every actor, with no bypass — not just discouraged by convention.

## What this does NOT change

- **Normal release-tag creation is unaffected.** `deletion` and `non_fast_forward` only apply to a tag that already exists; `release.yml`'s `gh release create "$TAG" ...` step (which creates the tag alongside the release) is a plain create against a not-yet-existing ref, never a delete or a force-update, so it's untouched by this ruleset.
- **Non-`v*` tags** (if any are ever created) are not covered — the pattern is scoped to `refs/tags/v*` specifically, matching this project's only tagging convention (`vX.Y.Z`, `vX.Y.Z-rc.N`).
- **Branches** are a separate concern from this ruleset (which targets `tag`, not `branch`) and are not addressed by RBI-POST-004.

## To reproduce or verify this configuration manually

Via the GitHub UI: **Settings → Rules → Rulesets → New ruleset → New tag ruleset**, target `refs/tags/v*`, enable **Restrict deletions** and **Block force pushes**, set enforcement to **Active**, leave bypass list empty.

Via the API (what was actually run for this finding):

```bash
gh api repos/ley338-gif/OpenRBI/rulesets -X POST --input - <<'EOF'
{
  "name": "protect-release-tags",
  "target": "tag",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/tags/v*"], "exclude": [] } },
  "rules": [ { "type": "deletion" }, { "type": "non_fast_forward" } ]
}
EOF
```

Verify it's active:

```bash
gh api repos/ley338-gif/OpenRBI/rulesets --jq '.[] | select(.name=="protect-release-tags")'
```
