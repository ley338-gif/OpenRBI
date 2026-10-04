# Release gates

This document defines the checks that must succeed for every OpenRBI release commit. The GitHub Actions `Release gates` job is the single fail-closed aggregate: it runs with `if: always()` and fails unless every job listed below completed successfully. It must be configured as a required status check for `main`.

Python quality also regenerates every committed Python dependency lock with the
pinned compiler and fails on any diff. The frontend build and audit use
`npm ci`, so an inconsistent Node workspace lock fails closed as well. See
[`dependencies.md`](dependencies.md) for the update procedure.

| Required capability | GitHub Actions evidence |
|---|---|
| Backend integration tests | `Backend integration tests` runs the complete pytest integration suite against PostgreSQL, Valkey, Session Agent, and the real Docker runtime, including the Segmented role-scoping tests against roles provisioned by `scripts/provision-segmented-db-roles.sh`. |
| Security regression tests | Host-level security tests run inside `Backend integration tests` after network-isolation rules are applied. |
| Fault-injection acceptance | The same isolated integration job destructively kills/restarts Browser Sandbox, Session Agent, backend, PostgreSQL, and Valkey; stops ClamAV; creates an orphan; interrupts startup and networking; and verifies Drain/Maintenance recovery with DB, container, capacity, audit, incident, warning, and user-error assertions. See [`fault-injection-acceptance.md`](fault-injection-acceptance.md). |
| LDAP/LDAPS integration | `LDAP integration tests` covers the provider and real HTTP login/admin-configuration flows against a throwaway TLS-enabled OpenLDAP server. |
| Browser end-to-end tests | `Frontend E2E tests (Playwright)` drives both portals in a real Chromium browser against a running Compact stack: login and MFA enrollment, a noVNC-connected Secure Browser session, logout, the admin pages and the user/admin listener boundary. |
| Backend build | The backend entry of `Image vulnerability scan (Trivy)` builds `backend/Dockerfile` before scanning it. |
| Session Agent build | The Session Agent entry of `Image vulnerability scan (Trivy)` builds `session-agent/Dockerfile` before scanning it. |
| Frontend build and TypeScript check | The frontend entry of `Image vulnerability scan (Trivy)` builds `frontend/Dockerfile`; that build runs `tsc -b` and Vite for both portals. |
| Browser sandbox build | The browser entry of `Image vulnerability scan (Trivy)` builds `docker/browser/Dockerfile` before scanning it. The integration job also builds the image used by lifecycle tests. |
| Image vulnerability scans | All four Trivy matrix entries must pass at CRITICAL severity. Any exception must identify and document a concrete CVE in `.trivyignore`. |
| Node dependency vulnerabilities | `Frontend dependency scan (npm audit)` audits the lockfile-resolved workspace at CRITICAL severity. |
| Repository secrets | `Secret scan (gitleaks)` scans the complete Git history, not only the checked-out tree. |
| Frontend secret boundary | The frontend dependency job builds both production portals and rejects backend-only secret identifiers in `dist`. |
| Python dependency vulnerabilities | Both entries of `Python dependency scan` audit the exact hash-verified backend and Session Agent production locks with `pip-audit --strict`. |
| Python lint | `Python lint and type checking` runs Ruff over application code, tests, and migrations. |
| Python type checking | The same job runs mypy independently for backend and Session Agent, avoiding their intentionally identical top-level `app` package names colliding. |
| Session Agent unit tests | The same job runs the Session Agent's pytest suite (`session-agent/tests/`, e.g. the capacity computation). |
| Version consistency | The same job runs `scripts/check-version-sync.py`, which fails if any package or image default differs from the root `VERSION`. |
| Toolchain consistency | The same job runs `scripts/check-toolchain-sync.py`, which fails if the Python lock target or any workflow's Python/Node version differs from the images' base runtimes (`FROM python:X.Y`, `FROM node:N`). |
| V1 acceptance manifest | The same job runs `scripts/check-v1-acceptance.py`, which requires all 35 binding scenarios, every prescribed result field, a PASS result, and non-empty evidence. The evidence itself is produced by the functional jobs in this table. |
| Documentation freeze | The same job runs `scripts/check-docs-freeze.py`, requiring the release/operator document set, rejecting known stale release claims, and resolving every local Markdown link in the root `*.md` files (including `SECURITY.md`), `frontend/README.md` and `docs/**`: the target file must exist, and a `#anchor` into a Markdown file must match one of its headings (GitHub's slug rules) or an explicit `<a id>`. |
| Configuration reference | The same job runs `scripts/check-config-docs.py`: `docs/configuration.md` must list every backend and Session Agent setting with the default the code uses, and every variable `.env.example` and the Compose files use. |
| API reference | The same job imports both apps and runs `scripts/generate-api-reference.py --check`, which fails when `docs/api-reference.md` differs from the current route tables, or when a route without an auth dependency isn't listed with the mechanism that protects it. |
| Migration validation | The backend integration, LDAP integration and Playwright E2E jobs each run `alembic upgrade head` against a fresh PostgreSQL database. Multiple heads, broken imports, or a migration that cannot build the current schema fail the job. |
| Fresh-install acceptance | `Fresh install acceptance` builds an isolated Compact installation from an empty volume, generates secrets, migrates, applies network isolation, bootstraps MFA, creates/logs in a user, and starts/terminates a real browser sandbox. |
| Backup/restore acceptance | `Backup and restore acceptance` records current-schema baseline counts and concrete user, policy, audit and quarantine evidence; runs the production backup; corrupts database rows and bytes; restores; then proves exact data, login, sandbox lifecycle, health and proxy behavior. |
| Upgrade acceptance | Two legs, `Upgrade acceptance (from 0.1.1)` and `Upgrade acceptance (from previous release)`, each preserve a reproducibly built baseline deployment — the pinned 0.1.1 commit, respectively the newest earlier GA tag — while replacing all four images with the target commit, running Alembic, and proving existing MFA/LDAP/users/policies/sessions/audit/quarantine/worker state plus live login/download/sandbox/proxy behavior. See [`upgrade-acceptance.md`](upgrade-acceptance.md). |

## Branch and release policy

- Never release directly from an unchecked commit.
- `main` must require the `Release gates` status check and disallow force pushes and branch deletion.
- A pull request may merge only after `Release gates` succeeds and relevant review feedback is resolved.
- A tag or GitHub Release must point to a commit already present on `main` whose `Release gates` result succeeded.
- Do not disable, soften, or bypass a failing check to publish a release.

After publication, `.github/workflows/acceptance-published.yml` repeats the
functional jobs above against the published images instead of local builds
([`release-process.md`](release-process.md) step 6).

The release workflow additionally re-verifies the successful `Release gates`
check on its exact commit before it builds or publishes anything. Its digest
recording and later artifact-specific checks complement these source and image
gates; they do not replace them. See [`publishing.md`](publishing.md).

Release builds additionally fail if any of the four image SBOMs cannot be
generated or validated as CycloneDX JSON. These are release-workflow checks,
not a substitute for the dependency and image vulnerability gates above.
