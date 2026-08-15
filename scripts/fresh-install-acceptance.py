"""Drive the API portion of the v1 fresh-install acceptance protocol.

Runs inside the freshly built backend image so it uses only production
dependencies and reaches the exact API process being accepted.
"""

import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pyotp

BASE = "http://localhost:8000"
ADMIN_USERNAME = "acceptance_admin"
ADMIN_PASSWORD = "Acceptance-Admin-Password-2026!"
USER_USERNAME = "acceptance_user"
USER_PASSWORD = "Acceptance-User-Password-2026!"


class ApiClient:
    def __init__(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, method: str, path: str, payload: dict | None = None, expected: int = 200) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{BASE}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                if response.status != expected:
                    raise AssertionError(f"{method} {path}: expected {expected}, got {response.status}")
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise AssertionError(f"{method} {path}: expected {expected}, got {exc.code}: {body}") from exc

    def post(self, path: str, payload: dict | None = None, expected: int = 200) -> dict:
        return self.request("POST", path, payload, expected)

    def get(self, path: str) -> dict:
        return self.request("GET", path)


def wait_for_next_totp(totp: pyotp.TOTP, previous: str) -> str:
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        code = totp.now()
        if code != previous:
            return code
        time.sleep(1)
    raise AssertionError("TOTP time step did not advance")


def wait_for_healthy(client: ApiClient) -> dict:
    deadline = time.monotonic() + 180
    last = None
    while time.monotonic() < deadline:
        last = client.get("/admin/health")
        if last["status"] == "HEALTHY":
            return last
        time.sleep(5)
    raise AssertionError(f"system did not become HEALTHY: {last}")


def main() -> None:
    setup_token = sys.argv[1]
    client = ApiClient()

    assert client.get("/setup/status") == {"setup_required": True}
    print("ACCEPT 09 initial setup is required on the empty database")

    created = client.post(
        "/setup/admin",
        {"setup_token": setup_token, "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    enrolled = client.post("/mfa/setup/enroll", {"mfa_token": created["mfa_token"]})
    secret = urllib.parse.parse_qs(urllib.parse.urlparse(enrolled["otpauth_uri"]).query)["secret"][0]
    totp = pyotp.TOTP(secret)
    enrollment_code = totp.now()
    confirmed = client.post(
        "/setup/mfa/confirm",
        {"mfa_token": created["mfa_token"], "code": enrollment_code},
    )
    assert confirmed["status"] == "ok" and confirmed["recovery_codes"]
    assert client.get("/setup/status") == {"setup_required": False}
    print("ACCEPT 10 initial ADMIN completed mandatory TOTP enrollment")

    client.post("/auth/logout")
    login = client.post("/auth/login", {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert login["status"] == "mfa_required" and login["mfa_token"]
    login_code = wait_for_next_totp(totp, enrollment_code)
    assert client.post("/auth/mfa/verify", {"mfa_token": login["mfa_token"], "code": login_code})["status"] == "ok"
    admin = client.get("/auth/me")
    assert admin["username"] == ADMIN_USERNAME and admin["role"] == "ADMIN" and admin["mfa_enabled"] is True
    print("ACCEPT 11 normal ADMIN password + live TOTP login succeeded")

    health = wait_for_healthy(client)
    unhealthy = [component for component in health["components"] if component["status"] != "HEALTHY"]
    assert not unhealthy, unhealthy

    user = client.post(
        "/admin/users",
        {"username": USER_USERNAME, "password": USER_PASSWORD, "role": "USER", "group_ids": []},
        expected=201,
    )
    assert user["username"] == USER_USERNAME and user["role"] == "USER"
    print("ACCEPT 12 ADMIN created a real local USER through the API")

    client.post("/auth/logout")
    user_login = client.post("/auth/login", {"username": USER_USERNAME, "password": USER_PASSWORD})
    assert user_login["status"] == "ok"
    me = client.get("/auth/me")
    assert me["username"] == USER_USERNAME and me["role"] == "USER"
    print("ACCEPT 13 USER login succeeded")

    session = client.post("/sessions", expected=201)
    assert session["status"] == "ACTIVE"
    session_id = session["id"]
    print(f"ACCEPT 14 real browser session became ACTIVE ({session_id})")

    terminated = client.post(f"/sessions/{session_id}/terminate")
    assert terminated["status"] == "TERMINATED"
    assert client.get(f"/sessions/{session_id}")["status"] == "TERMINATED"
    print("ACCEPT 15 browser session terminated and remained TERMINATED")

    liveness = client.get("/health")
    assert liveness["status"] == "ok"
    print("ACCEPT 16 liveness and aggregate dependency health are HEALTHY")


if __name__ == "__main__":
    main()
