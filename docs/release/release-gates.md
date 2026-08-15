# Release gates

This document defines the checks that must succeed for every OpenRBI release commit. The GitHub Actions `Release gates` job is the single fail-closed aggregate: it runs with `if: always()` and fails unless every job listed below completed successfully. It must be configured as a required status check for `main`.

Python quality also regenerates every committed Python dependency lock with the
pinned compiler and fails on any diff. The frontend build and audit use
`npm ci`, so an inconsistent Node workspace lock fails closed as well. See
[`dependencies.md`](dependencies.md) for the update procedure.

| Required capability | GitHub Actions evidence |
|---|---|
| Backend integration tests | `Backend integration tests` runs the complete pytest integration suite against PostgreSQL, Valkey, Session Agent, and the real Docker runtime. |
| Security regression tests | Host-level security tests run inside `Backend integration tests` after network-isolation rules are applied. |
| LDAP/LDAPS integration | `LDAP integration tests` covers the provider and real HTTP login/admin-configuration flows against a throwaway TLS-enabled OpenLDAP server. |
| Backend build | The backend entry of `Image vulnerability scan (Trivy)` builds `backend/Dockerfile` before scanning it. |
| Session Agent build | The Session Agent entry of `Image vulnerability scan (Trivy)` builds `session-agent/Dockerfile` before scanning it. |
| Frontend build and TypeScript check | The frontend entry of `Image vulnerability scan (Trivy)` builds `frontend/Dockerfile`; that build runs `tsc -b` and Vite for both portals. |
| Browser sandbox build | The browser entry of `Image vulnerability scan (Trivy)` builds `docker/browser/Dockerfile` before scanning it. The integration job also builds the image used by lifecycle tests. |
| Image vulnerability scans | All four Trivy matrix entries must pass at CRITICAL severity. Any exception must identify and document a concrete CVE in `.trivyignore`. |
| Node dependency vulnerabilities | `Frontend dependency scan (npm audit)` audits the lockfile-resolved workspace at CRITICAL severity. |
| Python dependency vulnerabilities | Both entries of `Python dependency scan` audit the exact hash-verified backend and Session Agent production locks with `pip-audit --strict`. |
| Python lint | `Python lint and type checking` runs Ruff over application code, tests, and migrations. |
| Python type checking | The same job runs mypy independently for backend and Session Agent, avoiding their intentionally identical top-level `app` package names colliding. |
| Version consistency | The same job runs `scripts/check-version-sync.py`, which fails if any package or image default differs from the root `VERSION`. |
| Migration validation | Both integration jobs run `alembic upgrade head` against a fresh PostgreSQL database. Multiple heads, broken imports, or a migration that cannot build the current schema fail the job. |
| Fresh-install acceptance | `Fresh install acceptance` builds an isolated Compact installation from an empty volume, generates secrets, migrates, applies network isolation, bootstraps MFA, creates/logs in a user, and starts/terminates a real browser sandbox. |
| Backup/restore acceptance | `Backup and restore acceptance` records current-schema baseline counts and concrete user, policy, audit and quarantine evidence; runs the production backup; corrupts database rows and bytes; restores; then proves exact data, login, sandbox lifecycle, health and proxy behavior. |
| Upgrade acceptance | `Upgrade acceptance` preserves a pinned, reproducibly built 0.1.1 deployment while replacing all four images with the target commit, running Alembic, and proving existing MFA/LDAP/users/policies/sessions/audit/quarantine/worker state plus live login/download/sandbox/proxy behavior. |

## Branch and release policy

- Never release directly from an unchecked commit.
- `main` must require the `Release gates` status check and disallow force pushes and branch deletion.
- A pull request may merge only after `Release gates` succeeds and relevant review feedback is resolved.
- A tag or GitHub Release must point to a commit already present on `main` whose `Release gates` result succeeded.
- Do not disable, soften, or bypass a failing check to publish a release.

The release workflow additionally re-verifies the successful `Release gates`
check on its exact commit before it builds or publishes anything. Its digest
recording and later artifact-specific checks complement these source and image
gates; they do not replace them. See [`publishing.md`](publishing.md).

Release builds additionally fail if any of the four image SBOMs cannot be
generated or validated as CycloneDX JSON. These are release-workflow checks,
not a substitute for the dependency and image vulnerability gates above.
