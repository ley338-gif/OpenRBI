from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The literal placeholder from .env.example — rejecting exactly this value
# (not just emptiness) closes a real gap: if two components both keep the
# unedited example value, a shared-secret check between them would silently
# "match" on a value that's sitting in git (Phase 20 hardening).
_PLACEHOLDER_SECRET = "changeme-generate-a-strong-secret"


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
    setup_token_ttl_seconds: int = 30 * 60

    totp_secret_encryption_key: str = ""

    # RBI-POST-003 — signs the CSRF double-submit cookie (app/core/csrf.py).
    # Generate with `openssl rand -hex 32`, same as the other secrets below.
    csrf_secret_key: str = ""

    # Restrictive default per the project's fail-closed philosophy (§24
    # allows this to be configured higher; MVP 1 has no per-group/per-policy
    # override yet — that's Phase 12).
    max_sessions_per_user: int = 1

    # Interim local staging path for intercepted downloads (Phase 13).
    # Replaced by a real quarantine-storage abstraction in Phase 15 — see
    # docs/quarantine.md.
    download_staging_dir: str = "/app/data/staging"
    download_poll_interval_seconds: float = 3.0
    # RBI-POST-016: checked against the size list_downloads() already
    # reports, before fetch_download() ever pulls the file's bytes into
    # memory (app/services/downloads.py) — nothing in that path streams,
    # so this is the only point an oversized file can be refused without
    # risking OOM. Default 500 MiB; deliberately generous rather than
    # tight, since the fail-closed behavior on exceeding it is a QUARANTINED
    # file an admin has to review, not a silent drop — the operational cost
    # of a too-tight default falls on every legitimate large download.
    download_max_size_bytes: int = 500 * 1024 * 1024

    clamav_host: str = "clamav"
    clamav_port: int = 3310

    # Roadmap Phase B / B1.10.1 — worker telemetry polling (app/core/
    # node_poller.py) and the thresholds app/services/worker_health.py uses
    # to derive HEALTHY/DEGRADED/OFFLINE. 15s keeps the dashboard reasonably
    # current without hammering the Session Agent (project brief's own "a
    # few seconds to a few tens of seconds" guidance); OFFLINE at 3x that
    # interval tolerates one or two missed polls (a slow response, a GC
    # pause) without flapping a healthy node to OFFLINE and back.
    node_poll_interval_seconds: float = 15.0
    node_heartbeat_stale_seconds: float = 45.0
    node_cpu_degraded_percent: float = 90.0
    node_ram_degraded_percent: float = 90.0
    # Roadmap B1.10.2 — the longest range the dashboard's own UI offers is
    # 7d; nothing older than that is ever queried, so nothing older than
    # that needs to stay in worker_metric_samples. Pruned opportunistically
    # by the same poll tick that inserts new samples (app/core/
    # node_poller.py) rather than a separate scheduled job.
    metrics_retention_days: int = 7

    # Productization v0.1.1 (docs/analysis/productization-v0.1.1-zone-separation.md,
    # docs/adr/0011-user-admin-listener-separation.md): which API surface this
    # process instance registers. "both" (the default) preserves MVP 1's
    # single-process behavior exactly — Compact/homelab/dev deployments never
    # need to touch this. "user"/"admin" let the *same* built image run as two
    # separate processes with disjoint router surfaces, so a compromise of one
    # never inherits the other's routes (RBAC alone already blocks a merely
    # curious authenticated user from crossing this line, but doesn't help if
    # the process itself is compromised — see the ADR for the full rationale).
    # A Literal type here means an invalid value is a pydantic ValidationError
    # at startup — the same fail-fast principle as the secret validators
    # above, not a runtime 500 on first request.
    listener_mode: Literal["user", "admin", "both"] = "both"

    # LDAP/LDAPS authentication (Roadmap Phase B / B1, docs/adr/0015) — an
    # equal, parallel option alongside local login, never a replacement.
    # Disabled by default; enabling it with an unencrypted ldap:// URI and
    # StartTLS turned off is a startup-time ValueError below, not a runtime
    # choice an operator can quietly make — see the ADR's fail-closed
    # rationale.
    ldap_enabled: bool = False
    ldap_server_uri: str = ""
    ldap_use_starttls: bool = True
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_base_dn: str = ""
    # {username} is substituted with the value the user typed at login,
    # never interpolated unescaped into a raw filter string — see
    # app/core/auth_providers/ldap.py's escaping.
    ldap_user_search_filter: str = "(sAMAccountName={username})"
    ldap_group_attribute: str = "memberOf"
    # Path to a PEM CA bundle to trust for LDAPS/StartTLS, in addition to
    # (not instead of) the OS trust store — set this when the directory's
    # certificate is issued by an internal/private CA. Empty means "OS
    # trust store only", never "skip verification": app/core/
    # auth_providers/ldap.py always sets OPT_X_TLS_REQUIRE_CERT=DEMAND
    # regardless of this value (RBI-POST-001) — there is deliberately no
    # setting anywhere that disables certificate verification.
    ldap_ca_cert_file: str = ""
    # Group DN -> OpenRBI role name (Roadmap B1.3, docs/admin-guide.md).
    # An LDAP user whose groups match none of these keys gets the
    # least-privileged USER role, never an implicit elevated default — see
    # app/services/ldap_provisioning.py's resolution precedence
    # (ADMIN > SECURITY_REVIEWER > USER when multiple groups match).
    # Pydantic parses this from a JSON object string in the environment.
    ldap_group_role_mapping: dict[str, str] = {}

    # Orphan-container reconciliation (app/core/orphan_reconciler.py):
    # a running openrbi.managed container whose BrowserSession row is
    # missing or already TERMINATED/FAILED is only acted on after being
    # seen as an orphan on this many *consecutive* poll cycles — avoids
    # tearing down a session that's mid-create_session() and hasn't
    # committed its DB row yet (docs/adr/0021).
    orphan_reconcile_interval_seconds: float = 300.0
    orphan_reconcile_grace_cycles: int = 2

    # Downloads/quarantine retention (app/core/quarantine_retention.py).
    # Two separate windows: RELEASED files are cheap to re-request (a fresh
    # 5-minute release token, app/core/release_tokens.py) and carry no
    # forensic value once delivered, so they're swept quickly with just
    # enough grace for a user to request the token again; QUARANTINED/
    # REJECTED files retain incident-review value and get a much longer
    # window (docs/adr/0022).
    quarantine_retention_released_hours: float = 24.0
    quarantine_retention_quarantined_days: float = 90.0
    quarantine_retention_interval_seconds: float = 3600.0

    # RBI-POST-002: read-only marker file scripts/setup-network-isolation.sh
    # writes on the Docker host after applying the DOCKER-USER iptables
    # blocklist. Bind-mounted read-only into this container
    # (docker-compose.yml) — the backend has no host privilege to check
    # iptables state itself, so this presence/freshness check is the whole
    # mechanism (app/services/health.py::check_network_isolation).
    network_isolation_marker_file: str = "/etc/openrbi/network-isolation/marker"
    # How old the marker's timestamp may be before it's no longer trusted
    # (DEGRADED instead of HEALTHY) — must be set well above
    # scripts/systemd/openrbi-network-isolation.timer's rerun interval so a
    # single missed/delayed run doesn't flap the status.
    network_isolation_max_staleness_seconds: float = 900.0

    @field_validator("session_agent_api_token", "totp_secret_encryption_key", "csrf_secret_key")
    @classmethod
    def _reject_missing_or_placeholder_secret(cls, value: str, info) -> str:
        if not value or value == _PLACEHOLDER_SECRET:
            raise ValueError(
                f"{info.field_name} must be set to a real generated secret (see .env.example) — "
                "refusing to start with a missing or unedited placeholder value"
            )
        return value

    @model_validator(mode="after")
    def _ldap_config_is_fail_closed(self) -> "Settings":
        if not self.ldap_enabled:
            return self
        if not self.ldap_server_uri.startswith(("ldaps://", "ldap://")):
            raise ValueError("OPENRBI_LDAP_SERVER_URI must start with ldaps:// or ldap://")
        if self.ldap_server_uri.startswith("ldap://") and not self.ldap_use_starttls:
            raise ValueError(
                "refusing to start: OPENRBI_LDAP_SERVER_URI uses plain ldap:// with "
                "OPENRBI_LDAP_USE_STARTTLS=false — an unencrypted bind is not a supported "
                "configuration (docs/adr/0015). Use ldaps:// or set OPENRBI_LDAP_USE_STARTTLS=true."
            )
        for field_name, value in (
            ("ldap_bind_dn", self.ldap_bind_dn),
            ("ldap_bind_password", self.ldap_bind_password),
            ("ldap_base_dn", self.ldap_base_dn),
        ):
            if not value or value == _PLACEHOLDER_SECRET:
                raise ValueError(
                    f"OPENRBI_{field_name.upper()} must be set when OPENRBI_LDAP_ENABLED=true — "
                    "refusing to start with a missing or unedited placeholder value"
                )
        _valid_roles = {"USER", "SECURITY_REVIEWER", "ADMIN"}
        for group_dn, role_name in self.ldap_group_role_mapping.items():
            if role_name not in _valid_roles:
                raise ValueError(
                    f"OPENRBI_LDAP_GROUP_ROLE_MAPPING maps '{group_dn}' to unknown role "
                    f"'{role_name}' — must be one of {sorted(_valid_roles)}"
                )
        if self.ldap_ca_cert_file and not Path(self.ldap_ca_cert_file).is_file():
            raise ValueError(
                f"OPENRBI_LDAP_CA_CERT_FILE is set to '{self.ldap_ca_cert_file}' but that file "
                "does not exist — refusing to start with a custom CA path that would silently "
                "fall back to no additional trust at connection time"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
