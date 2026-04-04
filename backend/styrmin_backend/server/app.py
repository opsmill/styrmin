"""This module serves as the entry point for the Styrmin FastAPI application."""

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from styrmin_backend import config
from styrmin_backend.api import init_graphql_router
from styrmin_backend.api.rest import init_rest_router
from styrmin_backend.db.utils import init_db, wait_for_database
from styrmin_backend.services.ingress_controller.driver import (
    initialize_internal_drivers,
)
from styrmin_backend.services.utilities.utilities import initialize_utilities
from styrmin_backend.workflows.dependency import get_manager

# Path to the built frontend assets (relative to repo root)
FRONTEND_DIST = (
    Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
)


async def app_initialization(_: FastAPI) -> None:
    """Initialize the application by setting up the database and logging.

    This function is called during the application startup phase.
    All necessary setup to be done before the application starts serving requests
    should be included here.
    """

    config.SETTINGS.initialize_and_exit()

    # Configure logging
    logger.remove(0)
    logger.add(sys.stderr, level=config.SETTINGS.log_level)

    # Wait for the database to become available, then initialize
    await wait_for_database()
    await init_db()

    # Initialize the Prefect manager
    prefect_manager = get_manager()
    await prefect_manager.initialize()  # type: ignore  # Prefect Flow.__call__ overload resolution

    # Initialize the utilities
    await initialize_utilities()

    # Initialize internal drivers (ingress controller)
    await initialize_internal_drivers()


async def shutdown(_: FastAPI) -> None:
    """Shutdown the application gracefully."""
    logger.info("Application shutdown complete")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator:
    await app_initialization(application)
    yield
    await shutdown(application)


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpsMill Styrmin-MVP Platform",
        lifespan=lifespan,
    )

    # CORS middleware for development (Vite dev server)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    # Setup the REST router
    app.include_router(init_rest_router())

    # Setup the GraphQL router
    app.include_router(init_graphql_router(), prefix="/graphql")

    # Serve frontend static files in production
    if FRONTEND_DIST.is_dir():
        # Serve bundled JS/CSS assets (directory may not exist in dev builds)
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        # Serve static files (favicon, etc.)
        app.mount("/static", StaticFiles(directory=FRONTEND_DIST), name="static")

        # SPA catch-all: serve index.html for any unmatched route so client-side
        # routing works on page refresh.
        index_html = FRONTEND_DIST / "index.html"

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str) -> FileResponse:  # noqa: ARG001
            return FileResponse(index_html)

    return app


app = create_app()
