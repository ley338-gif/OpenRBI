from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_health import router as admin_health_router
from app.api.admin_incidents import router as admin_incidents_router
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
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="OpenRBI Backend",
    version="0.1.0",
    description="OpenRBI control-plane API (MVP 1 under active development).",
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(mfa_router)
app.include_router(admin_router)
app.include_router(admin_sessions_router)
app.include_router(admin_quarantine_router)
app.include_router(admin_incidents_router)
app.include_router(admin_nodes_router)
app.include_router(admin_audit_router)
app.include_router(admin_health_router)
app.include_router(policies_router)
app.include_router(sessions_router)
app.include_router(files_router)
app.include_router(display_router)
