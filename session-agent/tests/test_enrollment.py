"""Roadmap B2.1 enrollment (app/enrollment.py) against the backend's CSRF
double-submit check. With OPENRBI_ENVIRONMENT != development the backend
marks the csrf_token cookie Secure; httpx's cookie jar never sends such a
cookie over plain http, so the agent has to echo it itself.
"""

import asyncio
from types import SimpleNamespace

import httpx

from app import enrollment


def test_enrollment_echoes_a_secure_csrf_cookie_over_plain_http(monkeypatch):
    seen: dict[str, str | None] = {}

    def backend(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok"},
                headers={"set-cookie": "csrf_token=nonce.sig; Path=/; SameSite=Strict; Secure"},
            )
        seen["cookie"] = request.headers.get("cookie")
        seen["csrf"] = request.headers.get("x-csrf-token")
        return httpx.Response(200, json={"status": "PENDING"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        enrollment.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(backend), **kwargs)
    )
    settings = SimpleNamespace(
        control_plane_url="http://backend:8000", enrollment_token="token", node_name="node-2", api_token="agent-token"
    )

    assert asyncio.run(enrollment._try_enroll_once(settings)) is True
    assert seen == {"cookie": "csrf_token=nonce.sig", "csrf": "nonce.sig"}
