from functools import lru_cache

from app.core.auth_providers.local import LocalAuthProvider


@lru_cache
def get_local_auth_provider() -> LocalAuthProvider:
    """Single seam for the local auth path (docs/adr/0015), mirroring
    session-agent/app/providers/factory.py's get_provider() pattern.
    Roadmap B1.2 adds a second provider here; B1.1 only moves the existing
    local path behind this interface, so there is exactly one provider for
    now.
    """
    return LocalAuthProvider()
