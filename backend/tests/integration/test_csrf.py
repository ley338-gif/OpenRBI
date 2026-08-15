"""RBI-POST-003 — CSRF protection (backend/app/core/csrf.py). Exercises
the real middleware against the live stack (see conftest.py's module
docstring) rather than mocking anything — the `client` fixture already
auto-attaches a valid token on every mutating request (mirroring the real
frontend's shared ApiClient), so the negative tests here explicitly
override that header per-request to probe the check itself.
"""

import httpx
import pytest

from tests.conftest import make_user


@pytest.mark.asyncio
async def test_valid_token_allows_login(client: httpx.AsyncClient, db):
    # The client fixture's event hook already attaches a valid token —
    # this is the baseline every negative test below is contrasted against.
    user, password = await make_user(db)
    r = await client.post("/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_missing_token_is_blocked(client: httpx.AsyncClient, db):
    user, password = await make_user(db)
    # Ensure this client already has a real, valid csrf_token cookie
    # before the probe — the point of this test is "cookie present, header
    # absent", not "neither exists yet".
    await client.get("/health")
    r = await client.post(
        "/auth/login",
        json={"username": user.username, "password": password},
        headers={"X-CSRF-Token": ""},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_wrong_token_is_blocked(client: httpx.AsyncClient, db):
    user, password = await make_user(db)
    await client.get("/health")
    r = await client.post(
        "/auth/login",
        json={"username": user.username, "password": password},
        headers={"X-CSRF-Token": "not-the-real-token.deadbeef"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_token_from_another_session_is_blocked(db):
    # Two independent clients, each with their own independently-random
    # csrf_token cookie — using session A's valid token as the header on a
    # request whose *cookie* is session B's must still fail: the header
    # must match THIS request's own cookie, not merely be some
    # server-issued token from somewhere.
    user, password = await make_user(db)
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as client_a:
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as client_b:
            await client_a.get("/health")
            await client_b.get("/health")
            token_a = client_a.cookies.get("csrf_token")
            token_b = client_b.cookies.get("csrf_token")
            assert token_a and token_b and token_a != token_b

            r = await client_b.post(
                "/auth/login",
                json={"username": user.username, "password": password},
                headers={"X-CSRF-Token": token_a},
            )
            assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_requests_are_never_blocked_by_csrf(client: httpx.AsyncClient):
    # No token attached at all (client fixture only attaches one for
    # mutating methods) — GET must be completely unaffected.
    r = await client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_cookie_is_issued_on_first_contact(db):
    # A brand new client, before ever logging in, still gets a valid
    # csrf_token cookie from a plain GET — required for the pre-auth
    # /auth/login POST above to be possible at all.
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as fresh_client:
        r = await fresh_client.get("/health")
        assert r.status_code == 200
        assert fresh_client.cookies.get("csrf_token")
