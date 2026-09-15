from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()


def _resolve_database_url() -> str:
    """Segmented-deployment credential scoping (docs/adr/0025).

    "both" mode (Compact's default) always uses the shared URL — splitting
    credentials for a single process that already holds every role is
    meaningless. "user"/"admin" mode uses its own scoped URL only if the
    operator actually set one; otherwise it falls back to the shared URL
    unchanged, so an un-opted-in Segmented deployment behaves exactly as
    before this ADR.
    """
    if settings.listener_mode == "user" and settings.database_url_user:
        return settings.database_url_user
    if settings.listener_mode == "admin" and settings.database_url_admin:
        return settings.database_url_admin
    return settings.database_url


# pool_pre_ping is deliberately NOT used here: SQLAlchemy's async pre-ping
# implementation has a known issue where its connection health-check can
# run outside the greenlet context the async dialect needs, raising
# "MissingGreenlet: greenlet_spawn has not been called" — reproduced during
# Phase 17 testing (a second sequential request reusing a pooled connection
# consistently failed this way). pool_recycle proactively discards
# connections before they'd go stale instead, without that failure mode.
engine = create_async_engine(_resolve_database_url(), pool_recycle=1800)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
