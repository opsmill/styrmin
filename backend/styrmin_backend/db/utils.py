import asyncio
from collections.abc import AsyncGenerator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend import config
from styrmin_backend.db.constants import DatabaseType

# Import the SQLModel class from the models module to make sure the models are loaded
from styrmin_backend.db.models import SQLModel

_async_engine: AsyncEngine | None = None


def get_database_url() -> str:
    """Construct the database URL based on configuration."""
    db_settings = config.SETTINGS.database

    # If full URL override is provided, use it
    if db_settings.db_url:
        return db_settings.db_url

    # SQLite: sqlite+aiosqlite:///path/to/db.db
    if db_settings.db_type == DatabaseType.SQLITE:
        return f"sqlite+aiosqlite:///{db_settings.db_name}"

    # PostgreSQL: postgresql+asyncpg://user:pass@host:port/dbname
    if db_settings.db_type == DatabaseType.POSTGRES:
        credentials = ""
        if db_settings.db_username:
            credentials = db_settings.db_username
            if db_settings.db_password:
                credentials += f":{db_settings.db_password}"
            credentials += "@"

        return f"postgresql+asyncpg://{credentials}{db_settings.db_host}:{db_settings.db_port}/{db_settings.db_name}"

    raise ValueError(f"Unsupported database type: {db_settings.db_type}")


def get_sync_database_url() -> str:
    """Return a synchronous database URL for Alembic offline mode."""
    url = get_database_url()
    return url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg2")


def get_async_engine() -> AsyncEngine:
    """Get the async database engine."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            get_database_url(), echo=config.SETTINGS.database.echo
        )
    return _async_engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    async with AsyncSession(get_async_engine(), expire_on_commit=False) as session:
        yield session


async def wait_for_database(max_retries: int = 10, retry_interval: float = 1.0) -> None:
    """Wait for the database to become available.

    Retries a simple ping query until the database responds or retries are exhausted.
    This prevents CrashLoopBackOff on fresh Kubernetes installs where the database
    container may not be ready when the application starts.
    """
    engine = get_async_engine()
    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database is ready")
            return
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            logger.warning(
                "Database not ready (attempt {}/{}): {}",
                attempt,
                max_retries,
                exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(retry_interval)

    msg = f"Database not available after {max_retries} retries"
    raise ConnectionError(msg) from last_exception


async def init_db() -> None:
    """Initialize the database."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
