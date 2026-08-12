from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Session Agent configuration.

    This service intentionally holds the only sandbox-runtime credentials in
    the system (see docs/adr/0004-separate-session-agent.md and
    0005-no-docker-socket-in-backend.md). Its API token must never be reused
    for any other service, and it must never be reachable from inside a
    browser sandbox.
    """

    model_config = SettingsConfigDict(env_prefix="OPENRBI_AGENT_", env_file=".env", extra="ignore")

    environment: str = "development"
    api_token: str = ""
    docker_base_url: str = "unix:///var/run/docker.sock"

    # Placeholder image for Phase 6 lifecycle testing — replaced by the real
    # hardened Firefox/noVNC image in Phase 7. Kept configurable so that
    # swap requires no provider-logic change (docs/adr/0003).
    sandbox_image: str = "alpine:3.20"
    sandbox_command: list[str] = ["sleep", "infinity"]
    sandbox_network_name: str = "bridge"

    # Defaults per the project brief §24; overridable per session by the
    # control plane's request payload.
    default_cpu_limit: float = 2.0
    default_ram_limit_mb: int = 2048
    default_pid_limit: int = 512
    default_disk_limit_mb: int = 2048


@lru_cache
def get_settings() -> Settings:
    return Settings()
