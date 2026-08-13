"""Second helper for scripts/verify-fresh-install.sh — run after the
backend container has been restarted, proving the bootstrap admin created
before the restart can still log in normally afterward (Section 16's
"restart, confirm admin can still log in" requirement).
"""

import json
import urllib.request

BASE = "http://localhost:8000"


def call(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main() -> None:
    result = call("/auth/login", {"username": "fresh_install_admin", "password": "FreshInstall-Pw2026!"})
    # mfa_enabled is already true from setup — a normal login now asks for
    # the live TOTP code, exactly like any other enrolled ADMIN.
    assert result["status"] == "mfa_required", result
    print("  OK: /auth/login for the bootstrap admin works after restart (requires the live TOTP code, as expected)")


if __name__ == "__main__":
    main()
