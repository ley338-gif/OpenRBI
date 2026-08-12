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

    # Hardened Firefox+Xvfb+x11vnc image built from docker/browser/ (Phase
    # 7). Its own ENTRYPOINT starts everything, so no command override is
    # needed. Kept configurable per docs/adr/0003 — swapping browser image
    # or engine later needs no provider-logic change.
    sandbox_image: str = "openrbi-browser:latest"
    sandbox_command: list[str] | None = None
    # TEMPORARY pending Phase 9 (network isolation): sandboxes join the same
    # docker network as the control plane so the backend can reach the VNC
    # port for Phase 8's display relay. This does NOT newly regress
    # anything — there is no egress filtering at all yet regardless of
    # which network is used, and Phase 9 is exactly where that gets built
    # (a dedicated, egress-filtered browser-plane network plus a
    # display-only path back to the control plane). Must be revisited then.
    sandbox_network_name: str = "openrbi_control-plane"

    # Defaults per the project brief §24; overridable per session by the
    # control plane's request payload.
    default_cpu_limit: float = 2.0
    default_ram_limit_mb: int = 2048
    default_pid_limit: int = 512
    default_disk_limit_mb: int = 2048


@lru_cache
def get_settings() -> Settings:
    return Settings()
