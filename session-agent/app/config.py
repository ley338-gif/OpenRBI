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

    # Roadmap B3.1 (docs/roadmap-b3-capacity-autoscaling.md) — capacity is
    # now computed from real free host headroom (see _capacity_from_settings()
    # in main.py), not a flat configured number. This is now a *ceiling* on
    # that computed value, not the value itself: unset (the default) means
    # uncapped — the computed number is reported as-is. An operator who
    # wants the old fixed-number behavior back sets this explicitly; that's
    # the only way OPENRBI_AGENT_CAPACITY still directly determines what's
    # reported, and only ever as an upper bound.
    #
    # Before Roadmap B3, this defaulted to 10 and *was* the reported
    # capacity outright (Roadmap B2.3). An operator who never set this
    # explicitly (the documented default single-node setup) sees reported
    # capacity change from a flat 10 to whatever this host's real headroom
    # computes to — a deliberate behavior change, not a bug; see B3.1's own
    # Definition of Done in the roadmap doc and CHANGELOG's Changed entry.
    capacity: int | None = None
    # Roadmap B3.1/B3.2 — RAM held back from the capacity computation for
    # the host OS, the Docker daemon, and this agent process itself, so
    # sandboxes are never sized to consume literally every free MB. 512 is a
    # conservative starting point for a typical Linux server host; tune per
    # docs/deployment.md#sizing once real headroom on a given host is known.
    reserved_ram_mb: int = 512
    # Roadmap B3.2 — asymmetric hysteresis on the computed capacity above:
    # a drop applies on the very next poll (fail-closed toward safety), but
    # a rise only applies once this many *consecutive* polls all sustain
    # the higher value — so a momentary host recovery blip doesn't
    # immediately reverse a real drop, and select_node() (backend,
    # Roadmap B2.3) doesn't see capacity flap on every single poll. See
    # _CapacityHysteresis in main.py.
    capacity_recovery_polls: int = 3
    # Dedicated, egress-filtered network (docker-compose.yml, scripts/
    # setup-network-isolation.sh) — sandboxes are never on the same network
    # as postgres/redis/session-agent. The backend is multi-homed onto this
    # network too (for the Phase 8 display relay), but the isolation script
    # only permits ESTABLISHED/RELATED traffic back across that boundary.
    sandbox_network_name: str = "openrbi_browser-plane"

    # Roadmap B2.1 (docs/adr/0023-node-enrollment-and-trust-model.md) —
    # both empty by default, matching the single-node case exactly as it
    # works today: the enrollment background task (app/main.py) only ever
    # runs when an operator deliberately sets enrollment_token, adding a
    # second/Nth node. control_plane_url is the *inverse* direction from
    # session_agent_base_url in backend/app/config.py — this is where
    # *this* agent calls *out* to the control plane, once, at startup.
    enrollment_token: str = ""
    control_plane_url: str = "http://backend:8000"

    # Defaults per the project brief §24; overridable per session by the
    # control plane's request payload.
    default_cpu_limit: float = 2.0
    default_ram_limit_mb: int = 2048
    default_pid_limit: int = 512
    default_disk_limit_mb: int = 2048
    default_screen_width: int = 1280
    default_screen_height: int = 800

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
