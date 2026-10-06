from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aiomysql
from fastapi import FastAPI
from pymongo import AsyncMongoClient, ReturnDocument

from db_test.config import settings

_mariadb_pool: aiomysql.Pool | None = None
_mongo_client: AsyncMongoClient | None = None  # type: ignore[type-arg]


async def _init_mariadb() -> None:
    global _mariadb_pool  # noqa: PLW0603
    _mariadb_pool = await aiomysql.create_pool(
        host=settings.mariadb_host,
        port=settings.mariadb_port,
        user=settings.mariadb_user,
        password=settings.mariadb_password,
        db=settings.mariadb_database,
        autocommit=True,
    )


async def _init_mongodb() -> None:
    global _mongo_client  # noqa: PLW0603
    _mongo_client = AsyncMongoClient(settings.mongodb_url)


# No database writes at startup: after a restore, this pod can start while the
# post-restore hooks reload the databases, and a seeded row would clash with them.
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    await _init_mariadb()
    await _init_mongodb()
    yield
    if _mariadb_pool:
        _mariadb_pool.close()
        await _mariadb_pool.wait_closed()
    if _mongo_client:
        _mongo_client.close()


app = FastAPI(title="DB Test", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/mariadb/count")
async def mariadb_count() -> dict[str, object]:
    assert _mariadb_pool is not None
    async with _mariadb_pool.acquire() as conn, conn.cursor() as cur:
        await cur.execute(
            "CREATE TABLE IF NOT EXISTS app_state (id INT PRIMARY KEY, counter INT NOT NULL DEFAULT 0)"
        )
        await cur.execute(
            "INSERT INTO app_state (id, counter) VALUES (1, 1) ON DUPLICATE KEY UPDATE counter = counter + 1"
        )
        await cur.execute("SELECT counter FROM app_state WHERE id = 1")
        row = await cur.fetchone()
        return {"counter": row[0], "backend": "mariadb"}


@app.get("/mongodb/count")
async def mongodb_count() -> dict[str, object]:
    assert _mongo_client is not None
    db = _mongo_client.get_default_database()
    result = await db.app_state.find_one_and_update(
        {"_id": 1},
        {"$inc": {"counter": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return {"counter": result["counter"], "backend": "mongodb"}
