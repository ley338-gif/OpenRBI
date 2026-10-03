# User Guide

> Status (Productization v0.1.1): a real User Portal now exists (`frontend/user/`), built against the User listener's API and verified end-to-end in a real browser against the live stack — login, MFA, a real Secure Browser session with a genuine noVNC connection to a real remote Firefox, uploads, and the real single-use-token download flow. The sections below describe the portal UI; the underlying API calls it makes are still documented beneath each section for anyone integrating directly instead.

## Logging in

Open the User Portal (Compact: the reverse proxy's root, e.g. `http://localhost:8080/`; Segmented: your organization's dedicated User Portal origin) and enter your username and password.

- If your account has no MFA yet and isn't in an MFA-mandatory role, you're taken straight to the dashboard.
- If MFA is already enabled, you're asked for a 6-digit code from your authenticator app. If you don't have the app at hand, enter one of your recovery codes in the same field instead.
- If your role requires MFA and you haven't enrolled yet, the portal walks you through enrollment (QR code, confirm code, one-time recovery codes) before you get a session — no separate step needed.

A wrong password, an unknown username, and a disabled account all show the identical "invalid credentials" message — this is deliberate, not a bug: there's no way to tell from the outside which of the three happened. Ten wrong attempts against the same username in 15 minutes locks it out, even if the very next attempt would have had the correct password (see [security-model.md#login-brute-force-protection-phase-20](security-model.md#login-brute-force-protection-phase-20)).

<details><summary>Underlying API</summary>

```
POST /auth/login   {"username": "...", "password": "..."}
```

Returns `{"status": "ok"}` (session cookie set), `{"status": "mfa_required", "mfa_token": "..."}`, or `{"status": "mfa_enrollment_required", "mfa_token": "..."}`.
</details>

## MFA enrollment and recovery codes

The portal shows a QR code — scan it with any TOTP authenticator app, then enter the 6-digit code it generates to confirm. **Your recovery codes are shown exactly once, immediately after** — the portal makes this explicit ("Store these recovery codes now. They will not be shown again.") and offers a one-click copy-to-clipboard. Each recovery code is single-use, for when you don't have your authenticator app available; there is no way to view them again later, by design — if you lose them, an administrator must reset your MFA and you'll enroll again.

Voluntary enrollment (if your role doesn't require it) works the same way from **Profile & Security** while already logged in.

## Dashboard

Shows your current MFA status, how many files you have on record, and your most recent session — all pulled live from the API, never placeholder data. The primary action is **Start Secure Browser**; if a session is already running, it becomes **Open Secure Browser** instead.

## Secure Browser

Click **Start Secure Browser**. You'll see the session progress through its real states — "Waiting for capacity…", "Preparing sandbox…", "Connecting display…" — before the remote browser actually appears. If no browser capacity is free at that moment, the portal says so ("No browser capacity is available right now. Try again shortly.") instead of starting a session. This is a genuine isolated Firefox instance running server-side; only pixels reach your browser over noVNC, and your session can reach the public internet but never the organization's internal network. The viewer uses all the space your window gives it — resize your browser and it recalculates to fill it, with no dead black borders.

A toolbar sits above the remote screen while a session is running:

- **Fit** / **100%** — scale the remote desktop to fill the viewer, or show it at its actual pixel size (useful for reading fine text; the viewer scrolls instead of shrinking further).
- **Clipboard** — sends whatever is on your local clipboard into the session. Text copied *inside* the remote session is picked up automatically and placed on your local clipboard the other way.
- **Fullscreen** — expands just the remote screen to fill your display, not the whole browser tab.
- **End session** — terminates the sandbox immediately; nothing about it (browsing history, cookies, downloads left in the sandbox) persists afterward.

If an administrator isolates your session, the portal tells you plainly: *"This session has been isolated by an administrator. Network access, uploads, and downloads are disabled."* — not a vague connection error. End that session and start a new one to continue.

You can upload a file into your active session from the same page — every upload is hashed, its real type detected, scanned, and policy-checked before it ever reaches the sandbox; you'll see a clear "blocked by policy" or "too large" message if it doesn't make it through, not a raw error.

## Downloads

Every file your session downloads is intercepted, scanned, and policy-checked before you can ever get it back (see [quarantine.md](quarantine.md)) — the Downloads page shows all of them with their real status, filterable by status, date and name, with a **Details** dialog per file. The status labels are **APPROVED** (released — has a **Download** button that requests a genuine single-use link and immediately starts the download), **PENDING** / **PENDING REVIEW** (still being scanned, or quarantined until an administrator decides), **BLOCKED** (rejected by policy, scanner result or reviewer) and **DELETED** (removed by the retention policy).

Approved files are kept for a limited time only — by default 24 hours after release — and are then deleted automatically (see [quarantine.md#retention](quarantine.md#retention)). Download a file you need soon after it is approved.

## Profile & Security

Shows your username, role, and account details, plus:

- **Multi-factor authentication** — **Set up MFA** if you haven't enrolled yet. Once enrolled, **Replace** lets you move to a new authenticator yourself: confirm with a current authenticator or recovery code, then **Reset and sign out** disables your MFA and signs you out on every device. If your role requires MFA, you enroll again at your next login. If you have lost both your authenticator and your recovery codes, an administrator has to reset your MFA instead.
- **Change password** — for accounts with an OpenRBI-managed (local) password, at least 12 characters. All your other login sessions are signed out afterwards. Directory (LDAP) accounts change their password in the directory, not here.
- **Secure Browser sessions** — your live sessions, each with an **End session** action (also useful for ending an isolated session).

## Logging out

**Log out** immediately invalidates your session server-side (sessions are Redis-backed, not self-contained tokens), not just in your browser.

---

<details><summary>Full underlying API reference (for direct integration)</summary>

```
POST /mfa/setup/enroll    {"mfa_token": "..."}   -> {"otpauth_uri": "...", "qr_code_png_base64": "..."}
POST /mfa/setup/confirm   {"mfa_token": "...", "code": "123456"}  -> {"status": "ok", "recovery_codes": [...]}
POST /mfa/enroll                       -> {"otpauth_uri": "...", "qr_code_png_base64": "..."}   (logged in, no mfa_token)
POST /mfa/enroll/confirm  {"code": "123456"}  -> {"recovery_codes": [...]}
POST /mfa/reset-self      {"code": "..."}     (current TOTP or recovery code; disables MFA and signs out every session)
POST /auth/mfa/verify     {"mfa_token": "...", "code": "123456"}   (code may also be a recovery code)
GET  /auth/me
POST /auth/change-password  {"current_password": "...", "new_password": "..."}   (local accounts only)

POST /sessions                        -> SessionResponse (QUEUED -> STARTING -> ACTIVE)
GET  /sessions/me                     -> your own sessions only
GET  /sessions/{id}                   -> 404 if it isn't yours, identical to a nonexistent id
POST /sessions/{id}/terminate
POST /sessions/{id}/uploads   (multipart, field "file")

GET  /files/me
GET  /files/me/page                   -> paginated, filterable list used by the Downloads page
POST /files/{id}/download-token       -> {"token": "...", "expires_in_seconds": 300}
GET  /files/download/{token}          -> single-use; a second request with the same token gets 401

POST /auth/logout
```

The noVNC display connects over WebSocket at `/api/display/{id}/ws`.
</details>
