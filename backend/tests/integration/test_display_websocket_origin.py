"""RBI-POST-024: the display WebSocket's origin check (app/api/display.py)
compares the client's Origin header against the Host header it actually
received. Found broken on real infrastructure: nginx's `$host` variable
silently strips a non-default port, but a real browser's Origin header
never does, so on any deployment not on port 80/443 -- including this
project's own documented default of 8080 -- the comparison always failed
and no real session could ever connect its display. No existing test
caught this because docker/nginx/nginx.conf's header forwarding can only
be exercised through the real reverse-proxy container -- see
scripts/fresh-install-acceptance.py's dedicated proxy-path check for
that. This suite instead pins the origin-vs-host comparison contract
itself directly against the backend, using the `websockets` client
against a real ACTIVE sandbox (real Session Agent, real Docker socket).
"""

import httpx
import pytest
import websockets
from websockets.exceptions import InvalidStatus

from app.services.sessions import create_session as create_session_service

from tests.conftest import login, make_user


@pytest.mark.asyncio
async def test_display_ws_accepts_matching_origin_and_host_with_a_nondefault_port(
    client: httpx.AsyncClient, db
):
    user, password = await make_user(db, role_name="USER")
    session = await create_session_service(db, user)
    await db.commit()
    cookie = await login(client, user.username, password)

    # A real browser's WS handshake always carries a matching, port-bearing
    # Origin and Host when both are derived from the same page URL -- this
    # is the exact scenario the reverse-proxy previously broke.
    async with websockets.connect(
        f"ws://localhost:8000/display/{session.id}/ws",
        additional_headers={
            "Origin": "http://localhost:8000",
            "Cookie": f"openrbi_session={cookie}",
        },
    ) as ws:
        assert ws.state.name == "OPEN"


@pytest.mark.asyncio
async def test_display_ws_rejects_a_genuinely_cross_origin_handshake(client: httpx.AsyncClient, db):
    user, password = await make_user(db, role_name="USER")
    session = await create_session_service(db, user)
    await db.commit()
    cookie = await login(client, user.username, password)

    with pytest.raises(InvalidStatus) as exc_info:
        async with websockets.connect(
            f"ws://localhost:8000/display/{session.id}/ws",
            additional_headers={
                "Origin": "http://evil.example.com:8000",
                "Cookie": f"openrbi_session={cookie}",
            },
        ):
            pass
    assert exc_info.value.response.status_code == 403
