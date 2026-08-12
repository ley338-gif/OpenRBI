# User Guide

> Status (Productization v0.1.1): a real User Portal now exists (`frontend/user/`), built against the User listener's API and verified end-to-end in a real browser against the live stack — login, MFA, a real Secure Browser session with a genuine noVNC connection to a real remote Firefox, uploads, and the real single-use-token download flow. The sections below describe the portal UI; the underlying API calls it makes are still documented beneath each section for anyone integrating directly instead.

## Logging in

Open the User Portal (Compact: the reverse proxy's root, e.g. `http://localhost:8080/`; Segmented: your organization's dedicated User Portal origin) and enter your username and password.

- If your account has no MFA yet and isn't in an MFA-mandatory role, you're taken straight to the dashboard.
- If MFA is already enabled, you're asked for a 6-digit code from your authenticator app.
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

Voluntary enrollment (if your role doesn't require it) works the same way from **Profile / MFA** while already logged in.

## Dashboard

Shows your current MFA status, how many files you have on record, and your most recent session — all pulled live from the API, never placeholder data. The primary action is **Start Secure Browser**; if a session is already running, it becomes **Open Secure Browser** instead.

## Secure Browser

Click **Start Secure Browser**. You'll see the session progress through its real states — "Waiting for capacity…", "Preparing sandbox…", "Connecting display…" — before the remote browser actually appears. This is a genuine isolated Firefox instance running server-side; only pixels reach your browser over noVNC, and your session can reach the public internet but never the organization's internal network.

If an administrator isolates your session, the portal tells you plainly: *"This session has been isolated by an administrator. Network access, uploads, and downloads are disabled."* — not a vague connection error. End that session and start a new one to continue.

**End session** terminates the sandbox immediately — nothing about it (browsing history, cookies, downloads left in the sandbox) persists afterward.

You can upload a file into your active session from the same page — every upload is hashed, its real type detected, scanned, and policy-checked before it ever reaches the sandbox; you'll see a clear "blocked by policy" or "too large" message if it doesn't make it through, not a raw error.

## Downloads

Every file your session downloads is intercepted, scanned, and policy-checked before you can ever get it back (see [quarantine.md](quarantine.md)) — the Downloads page shows all of them with their real status. A file marked **Released** has a **Download** button that requests a genuine single-use link and immediately starts the download; a file still **Quarantined** shows "Awaiting review" — an administrator must release it first.

## Profile / MFA

Shows your username, role, and current MFA status, with a **Set up MFA** action if you haven't enrolled yet. There is no self-service MFA *reset* here — that's an administrator-only action, correctly absent from this portal (and from the User API it talks to) entirely, not just hidden in the UI.

## Logging out

**Log out** immediately invalidates your session server-side (sessions are Redis-backed, not self-contained tokens), not just in your browser.

---

<details><summary>Full underlying API reference (for direct integration)</summary>

```
POST /mfa/setup/enroll    {"mfa_token": "..."}   -> {"otpauth_uri": "...", "qr_code_png_base64": "..."}
POST /mfa/setup/confirm   {"mfa_token": "...", "code": "123456"}  -> {"status": "ok", "recovery_codes": [...]}
POST /mfa/enroll / /mfa/enroll/confirm   (same shape, for a role that doesn't mandate MFA, while already logged in)
POST /auth/mfa/verify     {"mfa_token": "...", "code": "123456"}

POST /sessions                        -> SessionResponse (QUEUED -> STARTING -> ACTIVE)
GET  /sessions/me                     -> your own sessions only
GET  /sessions/{id}                   -> 404 if it isn't yours, identical to a nonexistent id
POST /sessions/{id}/terminate
POST /sessions/{id}/uploads   (multipart, field "file")

GET  /files/me
POST /files/{id}/download-token       -> {"token": "...", "expires_in_seconds": 300}
GET  /files/download/{token}          -> single-use; a second request with the same token gets 401

POST /auth/logout
```

The noVNC display connects over WebSocket at `/api/display/{id}/ws`.
</details>
