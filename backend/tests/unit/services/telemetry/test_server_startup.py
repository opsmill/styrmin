"""Where the server startup logs the telemetry line and creates the install ID (spec 020, FR-010, FR-014)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from styrmin_backend.config import TelemetrySettings
from styrmin_backend.server import app as server_app

STEPS = (
    "wait_for_database",
    "init_db",
    "bootstrap_default_admin_from_settings",
    "ensure_install_id",
    "initialize_utilities",
    "initialize_internal_drivers",
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []

    def record(name: str) -> AsyncMock:
        return AsyncMock(side_effect=lambda *_args: recorded.append(name))

    config = MagicMock()
    config.SETTINGS.log_level = "INFO"
    config.SETTINGS.telemetry = TelemetrySettings(enabled=False)
    logger = MagicMock()
    logger.info.side_effect = lambda message: recorded.append(f"info: {message}")
    manager = MagicMock(initialize=record("prefect_manager.initialize"))

    monkeypatch.setattr(server_app, "config", config)
    monkeypatch.setattr(server_app, "logger", logger)
    monkeypatch.setattr(server_app, "get_manager", lambda: manager)
    for step in STEPS:
        monkeypatch.setattr(server_app, step, record(step))
    return recorded


async def test_telemetry_line_comes_before_the_database_wait_and_the_id_after_the_schema(
    calls: list[str],
) -> None:
    await server_app.app_initialization(FastAPI())

    assert calls == [
        "info: Telemetry is off (STYRMIN_TELEMETRY_ENABLED=false).",
        "wait_for_database",
        "init_db",
        "bootstrap_default_admin_from_settings",
        "ensure_install_id",
        "prefect_manager.initialize",
        "initialize_utilities",
        "initialize_internal_drivers",
    ]
