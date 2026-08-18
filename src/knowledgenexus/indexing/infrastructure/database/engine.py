from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from knowledgenexus.indexing.infrastructure.database.models import Base


def to_async_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite+aiosqlite://"):
        return database_url
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


def ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return
    path_part = database_url.split("///", 1)[-1]
    if path_part == ":memory:":
        return
    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def create_engine(database_url: str) -> AsyncEngine:
    async_url = to_async_database_url(database_url)
    ensure_sqlite_parent_dir(async_url)
    connect_args = {"check_same_thread": False} if async_url.startswith("sqlite") else {}
    return create_async_engine(async_url, echo=False, connect_args=connect_args)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_database(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # The demo has already been run against SQLite databases created before
        # active_key existed.  Create-all deliberately does not alter an
        # existing table, so make this narrow additive migration explicit.
        if engine.url.get_backend_name() == "sqlite":
            columns = (await conn.execute(text("PRAGMA table_info(ingest_jobs)"))).mappings().all()
            if "active_key" not in {row["name"] for row in columns}:
                await conn.execute(text("ALTER TABLE ingest_jobs ADD COLUMN active_key VARCHAR(64)"))
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_ingest_jobs_active_key ON ingest_jobs(active_key)")
            )


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
