from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Mirrors the same check in backend/app/config.py — see that file's comment.
_PLACEHOLDER_SECRET = "changeme-generate-a-strong-secret"


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

    # Stable node identity for the control plane's BrowserNode row —
    # deliberately NOT the container's own hostname, which is ephemeral and
    # changes on every container recreation. Using it caused a real bug
    # (caught in Phase 18 testing): each rebuild created a new orphaned
    # BrowserNode row, and draining one had no effect on the live node
    # select_node() actually looks up. In a real multi-node deployment,
    # each node's agent is configured with its own distinct, stable name.
    node_name: str = "default-node"

    # Hardened Firefox+Xvfb+x11vnc image built from docker/browser/ (Phase
    # 7). Its own ENTRYPOINT starts everything, so no command override is
    # needed. Kept configurable per docs/adr/0003 — swapping browser image
    # or engine later needs no provider-logic change.
    sandbox_image: str = "openrbi-browser:latest"
    sandbox_command: list[str] | None = None
    # Dedicated, egress-filtered network (docker-compose.yml, scripts/
    # setup-network-isolation.sh) — sandboxes are never on the same network
    # as postgres/redis/session-agent. The backend is multi-homed onto this
    # network too (for the Phase 8 display relay), but the isolation script
    # only permits ESTABLISHED/RELATED traffic back across that boundary.
    sandbox_network_name: str = "openrbi_browser-plane"

    # Defaults per the project brief §24; overridable per session by the
    # control plane's request payload.
    default_cpu_limit: float = 2.0
    default_ram_limit_mb: int = 2048
    default_pid_limit: int = 512
    default_disk_limit_mb: int = 2048

    @field_validator("api_token")
    @classmethod
    def _reject_missing_or_placeholder_secret(cls, value: str, info) -> str:
        if not value or value == _PLACEHOLDER_SECRET:
            raise ValueError(
                f"{info.field_name} must be set to a real generated secret (see .env.example) — "
                "refusing to start with a missing or unedited placeholder value"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
