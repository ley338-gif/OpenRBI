from functools import lru_cache

from app.config import get_settings
from app.providers.docker_provider import DockerSandboxProvider


@lru_cache
def get_provider() -> DockerSandboxProvider:
    """Single seam for swapping providers (docs/adr/0003) — everything else
    in this service depends on the SandboxProvider protocol, not on this
    concrete class directly.
    """
    settings = get_settings()
    return DockerSandboxProvider(base_url=settings.docker_base_url)
