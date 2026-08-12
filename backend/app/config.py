from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, sourced from environment variables / .env.

    No default carries a real secret — every security-relevant value must be
    supplied explicitly at deploy time (fail closed on missing config, not on
    a convenient-but-insecure default).
    """

    model_config = SettingsConfigDict(env_prefix="OPENRBI_", env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str = "postgresql+asyncpg://openrbi:openrbi@postgres:5432/openrbi"
    redis_url: str = "redis://redis:6379/0"

    session_agent_base_url: str = "http://session-agent:8100"
    session_agent_api_token: str = ""

    session_cookie_name: str = "openrbi_session"
    session_ttl_seconds: int = 8 * 60 * 60

    totp_secret_encryption_key: str = ""

    # Restrictive default per the project's fail-closed philosophy (§24
    # allows this to be configured higher; MVP 1 has no per-group/per-policy
    # override yet — that's Phase 12).
    max_sessions_per_user: int = 1

    # Interim local staging path for intercepted downloads (Phase 13).
    # Replaced by a real quarantine-storage abstraction in Phase 15 — see
    # docs/quarantine.md.
    download_staging_dir: str = "/app/data/staging"
    download_poll_interval_seconds: float = 3.0

    clamav_host: str = "clamav"
    clamav_port: int = 3310


@lru_cache
def get_settings() -> Settings:
    return Settings()
