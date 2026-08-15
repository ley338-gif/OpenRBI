from fastapi import Response

from app.config import Settings, get_settings


def set_session_cookie(response: Response, token: str, config: Settings | None = None) -> None:
    """Apply the single, reviewed cookie policy to every login/MFA path."""
    settings = config or get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
    )


def clear_session_cookie(response: Response, config: Settings | None = None) -> None:
    settings = config or get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
    )
