# User Guide

> Status: like [admin-guide.md](admin-guide.md), this describes the real, usable backend API — there is no user portal UI yet (see [architecture.md#status](architecture.md#status)). Every step below is a real HTTP call against the deployed backend (`/api/*` through the reverse proxy).

## Logging in

```
POST /auth/login   {"username": "...", "password": "..."}
```

- If your account has no MFA yet and isn't in an MFA-mandatory role (ADMIN/SECURITY_REVIEWER), this immediately sets a session cookie and returns `{"status": "ok"}`.
- If MFA is already enabled on your account, you get `{"status": "mfa_required", "mfa_token": "..."}` — continue with **Completing a login with an existing TOTP code** below.
- If your role requires MFA and you haven't enrolled yet, you get `{"status": "mfa_enrollment_required", "mfa_token": "..."}` — continue with **First-time MFA enrollment** below. No session is issued on this path — a password alone is never enough for ADMIN/SECURITY_REVIEWER.

A wrong password, an unknown username, and a disabled account all return the identical `401 {"detail": "invalid credentials"}` — this is deliberate (no way to tell from the outside which of the three happened). Ten wrong attempts against the same username in 15 minutes locks that username out (`429`) even if the very next attempt would have had the correct password — see [security-model.md#login-brute-force-protection-phase-20](security-model.md#login-brute-force-protection-phase-20).

## First-time MFA enrollment (mandatory for ADMIN/SECURITY_REVIEWER)

```
POST /mfa/setup/enroll    {"mfa_token": "..."}   -> {"otpauth_uri": "...", "qr_code_png_base64": "..."}
```

Scan the QR code (or add the `otpauth_uri` manually) in any TOTP app, then:

```
POST /mfa/setup/confirm   {"mfa_token": "...", "code": "123456"}
-> {"status": "ok", "recovery_codes": ["...", ...]}
```

This sets the session cookie and enables MFA in one step. **The recovery codes are shown exactly once** — store them now. Each is single-use; using one records a `RECOVERY_CODE_USED` security event.

A USER account can enroll voluntarily the same way via `POST /mfa/enroll` + `POST /mfa/enroll/confirm` (identical shape) while already logged in, instead of the mandatory pre-session `/mfa/setup/*` path.

## Completing a login with an existing TOTP code (or a recovery code)

```
POST /auth/mfa/verify   {"mfa_token": "...", "code": "123456"}
```

`code` accepts either a live 6-digit TOTP code or one of your unused recovery codes — both are checked. Five wrong attempts against the same `mfa_token` invalidates it; log in again to get a fresh one.

## Starting and using a Secure Browser session

```
POST /sessions                        -> SessionResponse (status starts QUEUED, becomes ACTIVE once the sandbox is up)
GET  /sessions/me                     -> your own sessions only
GET  /sessions/{id}                   -> 404 if it isn't yours, identical to a nonexistent id
```

Once `ACTIVE`, connect the remote display over WebSocket at `/api/display/{id}/ws` (through the reverse proxy) with a noVNC client — this is what `frontend/src/SecureBrowserTest.tsx` does. Closing that WebSocket connection or losing network moves the session to `DISCONNECTED`; nothing about the sandbox itself is destroyed by a disconnect (an admin/reviewer can still act on it — see [admin-guide.md](admin-guide.md)).

Only one active session per user by default (`max_sessions_per_user`, see `.env.example`) — starting a second one while the first is still active/queued returns `429`.

```
POST /sessions/{id}/terminate         -> ends the session; the sandbox container is destroyed, nothing about it persists (ADR 0007)
```

## Uploading a file into your session

```
POST /sessions/{id}/uploads   (multipart, field "file")
```

The file is hashed, its real type detected from content (never trusted from its extension or declared content-type), checked against policy, and scanned — in that order, and only written into the sandbox if every step passes. A `DENY`/`QUARANTINE` policy verdict or a scanner outage blocks the upload immediately (`403`) rather than queuing it for review; there's no upload-side "pending" state like there is for downloads, since you're actively waiting on the result.

## Retrieving a released download

Every file your session downloads is intercepted, scanned, and policy-checked before you can ever get it back — see [quarantine.md](quarantine.md) for the full pipeline. Once a file's `status` is `RELEASED`:

```
GET  /files/me                              -> your own intercepted files, whatever their status
POST /files/{id}/download-token             -> {"token": "...", "expires_in_seconds": 300}   (only works on a RELEASED file you own)
GET  /files/download/{token}                -> the actual file bytes
```

The token is single-use (consuming it deletes it — a second request with the same token gets `401`) and expires after 5 minutes if never used. A file still `QUARANTINED` has no route to your machine yet — an ADMIN or SECURITY_REVIEWER must release it first (or reject it, in which case it never becomes available).

## Logging out

```
POST /auth/logout
```

Immediately invalidates the session server-side (sessions are Redis-backed, not self-contained tokens — see [security-model.md](security-model.md)), not just on your client.
