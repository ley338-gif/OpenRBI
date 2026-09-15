import hmac
from typing import Literal

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings


def _matches(presented: str, candidate: str) -> bool:
    """A never-configured candidate never matches, even an empty presented
    header — hmac.compare_digest("", "") is True, which would otherwise
    turn "this scope's token isn't configured" into "any caller is
    authenticated for it".
    """
    return bool(candidate) and hmac.compare_digest(presented, candidate)


def require_control_plane_token(required_scope: Literal["user", "admin"] = "admin"):
    """Authenticates calls from the control plane to this internal API and
    enforces the per-route scope (docs/adr/0025-segmented-credential-scoping.md).

    Fails closed: an unconfigured, missing, or mismatched/under-scoped
    token is always a 401, never an implicit allow.

    The legacy shared `api_token` and the scoped `api_token_admin` both
    satisfy either required scope — "admin" is a strict superset of
    "user" (admin/both-listener-mode background work, e.g. orphan
    reconciliation, still calls user-scope actions like terminate).
    `api_token_user` satisfies only `required_scope="user"`.

    Every configured candidate is compared unconditionally, in a fixed
    order, before combining the results — never short-circuited on the
    first match — so a caller can't distinguish "matched the admin
    token" from "matched the user token" by response timing.
    """

    async def _check(x_openrbi_agent_token: str = Header(default="")) -> None:
        settings = get_settings()
        is_full_access = _matches(x_openrbi_agent_token, settings.api_token) or _matches(
            x_openrbi_agent_token, settings.api_token_admin
        )
        is_user_scope = _matches(x_openrbi_agent_token, settings.api_token_user)
        authorized = is_full_access or (required_scope == "user" and is_user_scope)
        if not authorized:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent token")

    return _check


# Convenience pre-built dependencies for the common cases — avoids every
# route needing to write Depends(require_control_plane_token("user")) with
# a fresh closure per import.
require_user_scope = Depends(require_control_plane_token("user"))
require_admin_scope = Depends(require_control_plane_token("admin"))
