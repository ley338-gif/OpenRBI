"""Drive the API portion of the v1 fresh-install acceptance protocol.

Runs inside the freshly built backend image so it uses only production
dependencies and reaches the exact API process being accepted.
"""

import base64
import http.cookiejar
import json
import os
import socket
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

    def _csrf_token(self) -> str | None:
        for cookie in self.cookies:
            if cookie.name == "csrf_token":
                return cookie.value
        return None

    def request(self, method: str, path: str, payload: dict | None = None, expected: int = 200) -> dict:
        # RBI-POST-003: mutating requests need a matching X-CSRF-Token
        # header (app/core/csrf.py) — bootstrap the cookie with a cheap GET
        # first if this client doesn't have one yet, same as the real
        # frontend's shared ApiClient (frontend/shared/api/client.ts).
        if method != "GET" and self._csrf_token() is None:
            self.get("/health")
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if method != "GET":
            token = self._csrf_token()
            if token:
                headers["X-CSRF-Token"] = token
        request = urllib.request.Request(
            f"{BASE}{path}",
            data=data,
            headers=headers,
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

    def session_cookie(self) -> str:
        for cookie in self.cookies:
            if cookie.name == "openrbi_session":
                return cookie.value
        raise AssertionError("no openrbi_session cookie present")


def display_ws_handshake_status(session_id: str, session_cookie: str, *, host_header: str, origin_header: str) -> str:
    """Raw HTTP/1.1 WebSocket-upgrade handshake against the real
    reverse-proxy container (not the backend directly, unlike every other
    call in this script) — the only way to actually exercise
    docker/nginx/nginx.conf's header forwarding, which is exactly what a
    real browser's WS handshake goes through and every other check here
    bypasses. RBI-POST-024: nginx's $host variable silently strips a
    non-default port, but a real browser's Origin header never does, so
    app/api/display.py's origin-vs-host CSRF-equivalent check (a WS upgrade
    can't carry the app's normal X-CSRF-Token header) permanently rejected
    every real session on any deployment not on port 80/443 -- including
    this project's own documented default of 8080 -- until nginx was fixed
    to forward $http_host instead. No acceptance script caught it because
    every one of them, like every other call in this script, talks to the
    backend directly on its internal port, never through this proxy.
    Stdlib-only (no `websockets` package): this script runs inside the
    production backend image, which carries only its runtime dependencies.
    """
    request = (
        f"GET /api/display/{session_id}/ws HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\n"
        f"Origin: {origin_header}\r\n"
        f"Cookie: openrbi_session={session_cookie}\r\n"
        "\r\n"
    )
    with socket.create_connection(("reverse-proxy", 80), timeout=10) as sock:
        sock.sendall(request.encode())
        response = sock.recv(4096).decode(errors="replace")
    return response.split("\r\n", 1)[0]


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

    # RBI-POST-024: through the real reverse-proxy this time, matching what
    # a real browser's WS handshake actually goes through -- a same-origin
    # request whose Host/Origin both carry a real, non-default port (like
    # this project's own documented default of 8080) must be accepted, not
    # rejected by a proxy that silently drops the port off Host.
    cookie = client.session_cookie()
    same_origin_status = display_ws_handshake_status(
        session_id, cookie, host_header="openrbi.acceptance.test:8080", origin_header="http://openrbi.acceptance.test:8080"
    )
    assert same_origin_status.startswith("HTTP/1.1 101"), (
        f"real reverse-proxy path rejected a same-origin display WS handshake with a "
        f"non-default port: {same_origin_status}"
    )
    # A genuinely cross-origin handshake must still be rejected -- guards
    # against a future fix that weakens or removes the check entirely
    # instead of just correcting the port handling.
    cross_origin_status = display_ws_handshake_status(
        session_id, cookie, host_header="openrbi.acceptance.test:8080", origin_header="http://evil.example.com:8080"
    )
    assert not cross_origin_status.startswith("HTTP/1.1 101"), (
        f"real reverse-proxy path accepted a cross-origin display WS handshake: {cross_origin_status}"
    )
    print("ACCEPT 14b display WebSocket handshake through the real reverse-proxy enforces same-origin correctly")

    terminated = client.post(f"/sessions/{session_id}/terminate")
    assert terminated["status"] == "TERMINATED"
    assert client.get(f"/sessions/{session_id}")["status"] == "TERMINATED"
    print("ACCEPT 15 browser session terminated and remained TERMINATED")

    liveness = client.get("/health")
    assert liveness["status"] == "ok"
    print("ACCEPT 16 liveness and aggregate dependency health are HEALTHY")


if __name__ == "__main__":
    main()
