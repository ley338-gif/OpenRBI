import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_control_plane_token(x_openrbi_agent_token: str = Header(default="")) -> None:
    """Authenticates calls from the control plane to this internal API.

    Fails closed: an unconfigured or missing/mismatched token is always a
    401, never an implicit allow.
    """
    settings = get_settings()
    if not settings.api_token or not hmac.compare_digest(x_openrbi_agent_token, settings.api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent token")
