import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_dashboard import router as admin_dashboard_router
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
from app.api.node_enrollment import router as node_enrollment_router
from app.api.policies import router as policies_router
from app.api.sessions import router as sessions_router
from app.api.setup import router as setup_router
from app.build_info import BUILD_INFO
from app.config import get_settings
from app.core import node_poller, orphan_reconciler, quarantine_retention
from app.core.csrf import CSRFMiddleware
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
    #
    # Deliberately best-effort, never fatal: this project's own documented
    # install order (docs/deployment.md) — and CI's, .github/workflows/
    # ci.yml — is `docker compose up -d --build` *then* a separate
    # `alembic upgrade head`, i.e. the app is expected to start
    # successfully before its own schema exists yet. Before B1.9 nothing
    # at startup ever touched the database, so that ordering was safe
    # unconditionally; this is the one exception, and it must not turn a
    # missing/not-yet-migrated system_state table into the whole process
    # refusing to start (a real regression caught by CI, not assumed away
    # here) — a genuine DB outage at startup should still leave the
    # process up to serve /health honestly, not crash-loop.
    if settings.listener_mode in ("admin", "both"):
        try:
            async with async_session_factory() as db:
                token = await regenerate_setup_token(db)
        except Exception:
            logger.warning(
                "Could not check/generate the first-run setup token at startup "
                "(database not migrated yet?) — will retry on next restart.",
                exc_info=True,
            )
            token = None
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

    # Roadmap B1.10.1 — keeps worker telemetry current for the admin
    # monitoring UI regardless of session-creation traffic. Started only
    # where that UI is actually served; a user-only listener still gets
    # organic refreshes from select_node() on every session it creates.
    if settings.listener_mode in ("admin", "both"):
        node_poller.start()
        orphan_reconciler.start()
        quarantine_retention.start()

    yield
    node_poller.stop()
    orphan_reconciler.stop()
    quarantine_retention.stop()


app = FastAPI(
    title="OpenRBI Backend",
    version=BUILD_INFO.version,
    description="OpenRBI control-plane API.",
    lifespan=_lifespan,
)

# RBI-POST-003: the only middleware in the app — a second, independent
# layer of CSRF protection alongside SameSite=Lax (app/core/
# session_cookies.py). Applies uniformly across every listener mode since
# it wraps this one shared `app` object, before route registration below.
app.add_middleware(CSRFMiddleware)


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
    app.include_router(admin_dashboard_router)
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
    # Roadmap B2.1 — unauthenticated (a new node's own call has no admin
    # session), like setup_router, and for the same reason: only
    # meaningful on an admin-capable listener, closed by its own token +
    # rate limit instead of require_role (docs/adr/0023).
    app.include_router(node_enrollment_router)


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
