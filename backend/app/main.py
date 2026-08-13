import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_health import router as admin_health_router
from app.api.admin_incidents import router as admin_incidents_router
from app.api.admin_ldap import router as admin_ldap_router
from app.api.admin_mfa import router as admin_mfa_router
from app.api.admin_nodes import router as admin_nodes_router
from app.api.admin_quarantine import router as admin_quarantine_router
from app.api.admin_sessions import router as admin_sessions_router
from app.api.auth import router as auth_router
from app.api.display import router as display_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.mfa import router as mfa_router
from app.api.policies import router as policies_router
from app.api.sessions import router as sessions_router
from app.api.setup import router as setup_router
from app.config import get_settings
from app.db.session import async_session_factory
from app.services.setup_service import regenerate_setup_token

settings = get_settings()
logger = logging.getLogger("openrbi.setup")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Roadmap B1.9 — console-only setup token (Section 9): generated fresh
    # on every boot while the system is still uninitialized, printed once
    # to this process's own stdout/log, never exposed through any API. A
    # `user`-only listener never runs this — it has no /setup/* routes and
    # nothing in that process needs the token at all.
    if settings.listener_mode in ("admin", "both"):
        async with async_session_factory() as db:
            token = await regenerate_setup_token(db)
        if token:
            logger.warning(
                "\n"
                "==============================================================\n"
                "OpenRBI initial setup token:\n\n"
                "  %s\n\n"
                "Open the Admin Portal and enter this token, together with a\n"
                "username and password, to create the initial administrator.\n"
                "This token is invalidated once setup completes, and a new one\n"
                "is issued on every restart until then.\n"
                "==============================================================",
                token,
            )
    yield


app = FastAPI(
    title="OpenRBI Backend",
    version="0.1.0",
    description="OpenRBI control-plane API (MVP 1 under active development).",
    lifespan=_lifespan,
)


def _register_shared_routes(app: FastAPI) -> None:
    """Registered in every listener mode. Liveness and authentication have
    to work regardless of which API surface a given process is serving —
    an admin-mode process still needs its own login/MFA/logout, and a
    user-mode process needs the same. See docs/adr/
    0011-user-admin-listener-separation.md.
    """
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(mfa_router)


def _register_user_routes(app: FastAPI) -> None:
    """Self-service endpoints a normal USER account needs: own sessions,
    own files, the remote-display relay. Never includes anything gated by
    require_role("ADMIN"/"SECURITY_REVIEWER") — those routers don't even
    get imported here, they get excluded entirely (see module docstring
    note in docs/adr/0011-user-admin-listener-separation.md on why "not
    registered" beats "registered but 403").
    """
    app.include_router(sessions_router)
    app.include_router(files_router)
    app.include_router(display_router)


def _register_admin_routes(app: FastAPI) -> None:
    """Every router gated by require_role("ADMIN"/"SECURITY_REVIEWER"),
    plus admin_mfa (the one endpoint split out of the shared mfa router —
    see app/api/admin_mfa.py) and setup_router — deliberately NOT
    require_role-gated (there is no admin yet when it's used), but still
    only meaningful to an admin-capable listener, closed by its own
    persisted initialized flag/setup-token/rate-limit instead (Roadmap
    B1.9, docs/adr/0017-first-run-bootstrap.md).
    """
    app.include_router(admin_router)
    app.include_router(admin_sessions_router)
    app.include_router(admin_quarantine_router)
    app.include_router(admin_incidents_router)
    app.include_router(admin_ldap_router)
    app.include_router(admin_nodes_router)
    app.include_router(admin_audit_router)
    app.include_router(admin_health_router)
    app.include_router(policies_router)
    app.include_router(admin_mfa_router)
    app.include_router(setup_router)


# Single, central decision point for which API surface this process
# exposes (Productization v0.1.1) — deliberately not scattered across
# individual endpoints. OPENRBI_LISTENER_MODE defaults to "both", which
# reproduces MVP 1's exact prior behavior (every router, one process);
# Compact/homelab/dev deployments never need to set this. A user-mode
# process never imports/registers an admin router at all, so a request to
# an admin path is a plain FastAPI 404 (the route does not exist), not a
# 403 (the route exists and the caller lacked a role) — see docs/
# security-model.md for why that distinction is the actual point.
_register_shared_routes(app)
if settings.listener_mode in ("user", "both"):
    _register_user_routes(app)
if settings.listener_mode in ("admin", "both"):
    _register_admin_routes(app)
