from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# pool_pre_ping is deliberately NOT used here: SQLAlchemy's async pre-ping
# implementation has a known issue where its connection health-check can
# run outside the greenlet context the async dialect needs, raising
# "MissingGreenlet: greenlet_spawn has not been called" — reproduced during
# Phase 17 testing (a second sequential request reusing a pooled connection
# consistently failed this way). pool_recycle proactively discards
# connections before they'd go stale instead, without that failure mode.
engine = create_async_engine(settings.database_url, pool_recycle=1800)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
