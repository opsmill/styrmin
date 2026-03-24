import asyncio
import importlib.metadata

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from simple_app.database import get_engine, init_db
from simple_app.models import AppState


async def _upgrade() -> None:
    current_version = importlib.metadata.version("simple-app")

    await init_db()

    async with AsyncSession(get_engine()) as session:
        result = await session.exec(select(AppState).where(AppState.id == 1))
        state = result.one()
        old_version = state.version
        state.version = current_version
        session.add(state)
        await session.commit()

    print(f"Upgraded app version in database: {old_version} -> {current_version}")


def main() -> None:
    asyncio.run(_upgrade())


if __name__ == "__main__":
    main()
