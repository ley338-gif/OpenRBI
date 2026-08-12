from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.mfa import router as mfa_router
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
