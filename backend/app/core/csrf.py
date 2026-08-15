"""RBI-POST-003 — CSRF protection (signed double-submit cookie).

SameSite=Lax on the session cookie (app/core/session_cookies.py) was the
only defense before this; it's real but not complete (older/misbehaving
browsers, and it's a single layer). This adds a second, independent
layer: a non-HttpOnly `csrf_token` cookie the frontend reads and echoes
back as the `X-CSRF-Token` header on every state-changing request. A
cross-origin attacker page can trigger a request that automatically
carries the victim's cookies, but the Same-Origin Policy stops it from
*reading* csrf_token's value to construct a matching header — that
mismatch is the actual protection, independent of SameSite.

The cookie value is signed (HMAC-SHA256 over a random nonce, keyed by
OPENRBI_CSRF_SECRET_KEY) rather than a bare random value: an unsigned
double-submit cookie is defeated by any cookie-injection path (a
misconfigured sibling subdomain, a proxy that lets an attacker set
cookies for this origin) — the attacker sets one arbitrary value as both
the cookie and the forged header and the naive check passes. Signing
means a forged value's signature won't verify without the secret, so
mere cookie-injection isn't enough.

Deliberately NOT bound to the session token: the token must also work for
the two pre-authentication POST endpoints (/auth/login, /setup/*) where
no session exists yet. A CSRF cookie that's valid but doesn't match
*any* current session literally cannot exist as a bypass — its only
function is proving "this request's header came from something that
could read this origin's cookies", which a cross-site attacker can't do
regardless of which session (if any) is active.
"""

import hashlib
import hmac
import logging
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"

# GET/HEAD/OPTIONS must never have side effects (verified across every
# router in backend/app/api during RBI-POST-003) — only these are exempt.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

logger = logging.getLogger("openrbi.csrf")


def _sign(nonce: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()


def _new_token(secret: str) -> str:
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_sign(nonce, secret)}"


def _is_valid(token: str, secret: str) -> bool:
    try:
        nonce, signature = token.rsplit(".", 1)
    except ValueError:
        return False
    if not nonce or not signature:
        return False
    return hmac.compare_digest(_sign(nonce, secret), signature)


class CSRFMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware, to avoid its known
    streaming-response caveats) — validates state-changing requests and
    issues/refreshes the CSRF cookie on every HTTP response. WebSocket
    scopes pass through untouched (see app/api/display.py for that
    surface's own Origin-based defense).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        settings = get_settings()

        if request.method not in _SAFE_METHODS:
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
            header_token = request.headers.get(CSRF_HEADER_NAME, "")
            valid = (
                bool(cookie_token)
                and bool(header_token)
                and hmac.compare_digest(cookie_token, header_token)
                and _is_valid(cookie_token, settings.csrf_secret_key)
            )
            if not valid:
                logger.warning(
                    "CSRF check failed: %s %s (cookie_present=%s, header_present=%s)",
                    request.method,
                    request.url.path,
                    bool(cookie_token),
                    bool(header_token),
                )
                response = JSONResponse(
                    {"detail": "CSRF token missing or invalid"}, status_code=403
                )
                await response(scope, receive, send)
                return

        # Issue a fresh cookie whenever the caller doesn't already have a
        # valid one — covers first-ever visit (pre-login) and an expired/
        # tampered cookie alike. A caller that already has a valid one
        # just gets the same cookie re-set (cheap, avoids a second
        # code path for "refresh vs issue").
        existing = request.cookies.get(CSRF_COOKIE_NAME, "")
        needs_cookie = not (existing and _is_valid(existing, settings.csrf_secret_key))
        token = existing if not needs_cookie else _new_token(settings.csrf_secret_key)

        if not needs_cookie:
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                cookie_value = (
                    f"{CSRF_COOKIE_NAME}={token}; Max-Age={settings.session_ttl_seconds}; "
                    f"Path=/; SameSite=Lax"
                    + ("; Secure" if settings.environment != "development" else "")
                )
                headers.append((b"set-cookie", cookie_value.encode("utf-8")))
            await send(message)

        await self.app(scope, receive, send_with_cookie)
