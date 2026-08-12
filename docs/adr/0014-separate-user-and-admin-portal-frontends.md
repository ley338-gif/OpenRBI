# ADR 0014: Separate User Portal and Admin Portal frontends, one shared codebase

## Status

Accepted

## Context

Following [ADR 0011](0011-user-admin-listener-separation.md)'s backend listener split, OpenRBI needed real, working UIs (Productization v0.1.1's remaining scope) rather than the Phase 8 noVNC test harness. Building one combined SPA covering both roles would have reproduced the exact coupling ADR 0011 exists to avoid — a single frontend bundle whose code (and therefore whose XSS/supply-chain blast radius) contains every admin capability regardless of who's actually using it, and which frontend build would need to be pointed at the same origin for both roles, making the eventual Segmented profile (distinct origins per [ADR 0012](0012-compact-vs-segmented-deployment.md)) a retrofit instead of the default shape.

## Decision

Two separate Vite/React/TypeScript SPAs — `frontend/user/` and `frontend/admin/` — sharing common code from `frontend/shared/` (API client, auth/MFA flow, UI primitives, design tokens) via an npm workspace, not a published package. Each portal:

- Talks only to the listener mode it's meant for. The Admin Portal's API client (`frontend/admin/src/api/adminApi.ts`) only calls endpoints verified to exist on an `admin`-mode backend's own OpenAPI schema; the User Portal's (`frontend/user/src/api/userApi.ts`) only calls `user`-mode endpoints. Neither assumes it can fall back to the other listener's routes.
- Gets its own configurable API base URL (`VITE_API_BASE_URL`), so Compact (same-origin `/api`) and a future Segmented deployment (separate origins) need no code change, only different build-time env vars.
- Ships as its own build output — in Compact, both are packaged into one nginx image at `/` (User) and `/admin/` (Admin) for convenience (`frontend/Dockerfile`); in the illustrative Segmented example, each would get its own dedicated container/origin.

Session cookies are the only credential either portal ever holds — no client-side token storage, no separate frontend-side auth logic. Both portals use the exact same shared `AuthProvider`/`LoginFlow` (`frontend/shared/auth/`) talking to the same shared backend endpoints (`/auth/*`, `/mfa/*`), since those are registered in every listener mode.

## Alternatives Considered

- **One combined SPA with role-based UI hiding** — the obviously-rejected option: it would put every admin capability's code in the same bundle a normal user's browser downloads, contradicting the entire point of ADR 0011. Also would need client-side role checks duplicating what `require_role` already enforces server-side, and would still need retrofitting for the Segmented profile later.
- **Fully independent codebases (no `shared/`) for each portal** — considered and rejected: the auth/MFA flow, API-error handling, and basic UI primitives are identical logic serving two audiences, not two different products; duplicating them would mean fixing the same bug twice.
- **A generated/codegen API client from the OpenAPI schema** — considered (section 47 of the productization brief explicitly asks this be evaluated) and rejected for this schema's current size: hand-written, narrowly-scoped `userApi`/`adminApi` modules (one file each) are easier to audit against "does this call actually exist on this listener" than a generated client would be, and avoid adding a codegen toolchain dependency for ~50 endpoints. Revisit if the API surface grows substantially.

## Consequences

- A compromise of the User Portal's frontend bundle (e.g. a supply-chain issue in one of its few dependencies) cannot expose Admin Portal code, because that code was never bundled into it in the first place — a real, verified property (both apps' production builds were inspected; the admin bundle contains no `/sessions`/`/files`/`/display` routes and vice versa, confirmed via each listener's own OpenAPI schema during testing).
- The Compact deployment's single nginx container serving both portals at different paths is **not** a network boundary (see [ADR 0011](0011-user-admin-listener-separation.md) and `docs/security-model.md`) — both still share the same origin, same session cookie scope, and the same `both`-mode backend. This is documented, not silently implied to be more isolated than it is.
- Building the User Portal's real Secure Browser flow against the live stack surfaced two genuine, previously-latent bugs in code this ADR's frontends now exercise for the first time in a real browser (not just via API scripts): a React ref-timing race in the noVNC connect sequence, and a session-status write race between `terminate_session` and the display WebSocket's own close handler. The first was fixed in the frontend; the second is a pre-existing backend concurrency issue, documented as a known limitation rather than fixed here (see CHANGELOG and the productization report).
- Adding an automated, no-mock Playwright E2E suite (`frontend/e2e/`) on top of that same manual testing caught two more real bugs manual click-through had missed: `FormField`'s `<label>` had no real association with its input (a genuine accessibility gap, not a test-only concern), and the MFA-enrollment flow's `refresh()` call was placed early enough to make the `/login` route redirect away from the recovery-codes screen before a user could ever see it — a fully deterministic bug under React's update batching, not a flaky one. Both fixed; see CHANGELOG.
