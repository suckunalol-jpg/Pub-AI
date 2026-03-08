from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

_connect_args = {}
_engine_kwargs = {"echo": False}

_db_url = settings.DATABASE_URL
if _db_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
else:
    # Railway gives postgresql:// but asyncpg needs postgresql+asyncpg://
    if _db_url.startswith("postgresql://"):
        _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    _engine_kwargs.update({"pool_size": 20, "max_overflow": 10})

engine = create_async_engine(_db_url, connect_args=_connect_args, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
