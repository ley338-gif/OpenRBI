"""Helper for scripts/verify-fresh-install.sh — runs inside the throwaway
backend container itself (stdlib + pyotp only, both already in the
production image; no test-only dependency needed) and drives the exact
same three-endpoint sequence the Admin Portal's SetupFlow component does.
"""

import json
import sys
import urllib.parse
import urllib.request

import pyotp

BASE = "http://localhost:8000"


def call(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}") as resp:
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
