# Changelog

All notable changes to this project are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/), and this project does not yet follow semantic versioning (pre-alpha).

## [Unreleased]

### Added

- Project foundation: repository layout, initial documentation set, ADRs for the core architectural decisions, docker-compose skeleton, backend/session-agent/frontend scaffolding.
- Relational data model (§27 of the project brief) and Alembic migrations: `User`, `Role`, `Group`, `UserGroup`, `RecoveryCode`, `Policy`, `PolicyVersion`, `GroupPolicy`, `FilePolicyRule`, `BrowserSession`, `BrowserNode`, `QuarantineFile`, `Incident`, `SecurityEvent`. Default MVP roles (`USER`, `SECURITY_REVIEWER`, `ADMIN`) are seeded by migration.
- Local authentication: Argon2 password hashing, `POST /auth/login` / `POST /auth/logout` / `GET /auth/me`, server-side sessions in Redis (revocable, not JWTs), generic 401 on any login failure (no username enumeration), `USER_LOGIN`/`USER_LOGIN_FAILED` security events. Users with `mfa_enabled` get a short-lived MFA-pending token instead of a full session — completed by Phase 4 (TOTP MFA, not yet implemented).

### Fixed

- `clamav/clamav:1.3` in `docker-compose.yml` did not exist upstream; pinned to `1.5.4`.
