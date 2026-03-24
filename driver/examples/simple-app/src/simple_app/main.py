import importlib.metadata
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from simple_app.database import get_session, init_db
from simple_app.models import AppState


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield


app = FastAPI(title="Simple App", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/count")
async def count(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    result = await session.exec(select(AppState).where(AppState.id == 1))
    state = result.one()
    state.counter += 1
    session.add(state)
    await session.commit()
    await session.refresh(state)
    return {
        "counter": state.counter,
        "version": state.version,
    }


@app.get("/version")
async def version() -> dict[str, str]:
    return {"version": importlib.metadata.version("simple-app")}


@app.get("/probe")
async def probe(target: str = Query(..., description="DNS name or URL to probe")) -> dict[str, object]:
    """Probe a target DNS name via HTTP GET and return the response."""
    url = target if target.startswith("http") else f"http://{target}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            return {"status": response.status_code, "body": response.text}
    except Exception as exc:
        return {"status": 0, "body": str(exc)}
