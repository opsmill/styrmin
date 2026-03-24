from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from simple_app.config import settings
from simple_app.models import AppState  # noqa: F401 - Required for metadata registration

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = create_async_engine(settings.database_url)
    return _engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield session


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(engine) as session:
        result = await session.exec(select(AppState).where(AppState.id == 1))
        if result.first() is None:
            session.add(AppState(id=1, counter=0, version="unknown"))
            await session.commit()
