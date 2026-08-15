# Release gates

This document defines the checks that must succeed for every OpenRBI release commit. The GitHub Actions `Release gates` job is the single fail-closed aggregate: it runs with `if: always()` and fails unless every job listed below completed successfully. It must be configured as a required status check for `main`.

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
| Python dependency vulnerabilities | Both entries of `Python dependency scan` resolve and audit the backend and Session Agent production dependencies with `pip-audit --strict`. |
| Python lint | `Python lint and type checking` runs Ruff over application code, tests, and migrations. |
| Python type checking | The same job runs mypy independently for backend and Session Agent, avoiding their intentionally identical top-level `app` package names colliding. |
| Version consistency | The same job runs `scripts/check-version-sync.py`, which fails if any package or image default differs from the root `VERSION`. |
| Migration validation | Both integration jobs run `alembic upgrade head` against a fresh PostgreSQL database. Multiple heads, broken imports, or a migration that cannot build the current schema fail the job. |

## Branch and release policy

- Never release directly from an unchecked commit.
- `main` must require the `Release gates` status check and disallow force pushes and branch deletion.
- A pull request may merge only after `Release gates` succeeds and relevant review feedback is resolved.
- A tag or GitHub Release must point to a commit already present on `main` whose `Release gates` result succeeded.
- Do not disable, soften, or bypass a failing check to publish a release.

The later release workflow may add artifact-specific checks such as SBOM generation and digest recording. Those complement these source and image gates; they do not replace them.
