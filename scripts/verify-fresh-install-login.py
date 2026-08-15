"""Second helper for scripts/verify-fresh-install.sh — run after the
backend container has been restarted, proving the bootstrap admin created
before the restart can still log in normally afterward (Section 16's
"restart, confirm admin can still log in" requirement).
"""

import http.cookiejar
import json
import urllib.request

BASE = "http://localhost:8000"

_cookies = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies))


def call(path: str, payload: dict) -> dict:
    # RBI-POST-003: a mutating POST (this is /auth/login) needs a matching
    # X-CSRF-Token header (app/core/csrf.py) — bootstrap the cookie with a
    # cheap GET first, same as the real frontend's shared ApiClient
    # (frontend/shared/api/client.ts).
    _opener.open(urllib.request.Request(f"{BASE}/health"), timeout=30).close()
    csrf_token = next((c.value for c in _cookies if c.name == "csrf_token"), None)
    headers = {"Content-Type": "application/json"}
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(payload).encode(), headers=headers, method="POST")
    with _opener.open(req) as resp:
        return json.load(resp)


def main() -> None:
    result = call("/auth/login", {"username": "fresh_install_admin", "password": "FreshInstall-Pw2026!"})
    # mfa_enabled is already true from setup — a normal login now asks for
    # the live TOTP code, exactly like any other enrolled ADMIN.
    assert result["status"] == "mfa_required", result
    print("  OK: /auth/login for the bootstrap admin works after restart (requires the live TOTP code, as expected)")


if __name__ == "__main__":
    main()
