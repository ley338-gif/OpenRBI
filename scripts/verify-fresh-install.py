"""Helper for scripts/verify-fresh-install.sh — runs inside the throwaway
backend container itself (stdlib + pyotp only, both already in the
production image; no test-only dependency needed) and drives the exact
same three-endpoint sequence the Admin Portal's SetupFlow component does.
"""

import http.cookiejar
import json
import sys
import urllib.parse
import urllib.request

import pyotp

BASE = "http://localhost:8000"

_cookies = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies))


def call(path: str, payload: dict) -> dict:
    # RBI-POST-003: mutating POSTs need a matching X-CSRF-Token header
    # (app/core/csrf.py) — bootstrap the cookie with a cheap GET first,
    # same as the real frontend's shared ApiClient
    # (frontend/shared/api/client.ts).
    if not any(c.name == "csrf_token" for c in _cookies):
        get(path="/health")
    csrf_token = next((c.value for c in _cookies if c.name == "csrf_token"), None)
    headers = {"Content-Type": "application/json"}
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(payload).encode(), headers=headers, method="POST")
    with _opener.open(req) as resp:
        return json.load(resp)


def get(path: str) -> dict:
    with _opener.open(f"{BASE}{path}") as resp:
        return json.load(resp)


def main() -> None:
    token = sys.argv[1]

    result = call("/setup/admin", {"setup_token": token, "username": "fresh_install_admin", "password": "FreshInstall-Pw2026!"})
    mfa_token = result["mfa_token"]
    print("  OK: POST /setup/admin created the administrator")

    enroll = call("/mfa/setup/enroll", {"mfa_token": mfa_token})
    query = urllib.parse.urlparse(enroll["otpauth_uri"]).query
    secret = dict(p.split("=") for p in query.split("&"))["secret"]
    print("  OK: POST /mfa/setup/enroll (existing, unmodified endpoint) returned a QR/secret")

    still_required = get("/setup/status")["setup_required"]
    assert still_required is True, "setup completed before MFA confirm — should still be required"

    code = pyotp.TOTP(secret).now()
    confirm = call("/setup/mfa/confirm", {"mfa_token": mfa_token, "code": code})
    assert confirm["status"] == "ok"
    assert len(confirm["recovery_codes"]) > 0
    print("  OK: POST /setup/mfa/confirm succeeded, recovery codes issued")

    now_required = get("/setup/status")["setup_required"]
    assert now_required is False, "setup_required still true after a successful confirm"
    print("  OK: GET /setup/status now reports setup_required=false")


if __name__ == "__main__":
    main()
