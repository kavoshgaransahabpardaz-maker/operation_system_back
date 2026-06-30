from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import create_engine

from app.core.config import settings


# Async engine for FastAPI routes
async_engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Sync engine for Celery tasks
sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


async def get_async_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_sync_db():
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()
