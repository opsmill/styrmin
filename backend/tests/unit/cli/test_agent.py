"""Tests for the agent management commands."""

import sys
import types

import pytest
from pytest_mock import MockerFixture

from styrmin_backend.cli.agent import agent_app


def test_agent_start_loads_settings_before_importing_the_operator(
    mocker: MockerFixture,
) -> None:
    """Invalid settings must be reported before handler modules read them at import."""
    calls: list[str] = []
    mock_config = mocker.patch("styrmin_backend.cli.agent.config")
    mock_config.SETTINGS.initialize_and_exit.side_effect = lambda: calls.append(
        "settings"
    )

    def import_attribute(name: str) -> object:
        if name != "main":
            raise AttributeError(name)
        calls.append("import main")
        return mocker.Mock()

    combined = types.ModuleType("styrmin_backend.entrypoint.combined")
    combined.__getattr__ = import_attribute  # type: ignore[method-assign]
    mocker.patch.dict(sys.modules, {"styrmin_backend.entrypoint.combined": combined})
    mocker.patch("styrmin_backend.cli.agent.asyncio")

    with pytest.raises(SystemExit) as exc_info:
        agent_app(["start"])

    assert exc_info.value.code == 0
    assert calls == ["settings", "import main"]


def test_agent_start_passes_the_loaded_settings_to_the_entrypoint(
    mocker: MockerFixture,
) -> None:
    mock_config = mocker.patch("styrmin_backend.cli.agent.config")
    main = mocker.Mock()
    combined = types.ModuleType("styrmin_backend.entrypoint.combined")
    combined.main = main  # type: ignore[attr-defined]
    mocker.patch.dict(sys.modules, {"styrmin_backend.entrypoint.combined": combined})
    mocker.patch("styrmin_backend.cli.agent.asyncio")

    with pytest.raises(SystemExit):
        agent_app(["start", "--work-pool", "pool", "--no-clusterwide"])

    main.assert_called_once_with(
        settings=mock_config.SETTINGS.initialize_and_exit.return_value,
        work_pool_name="pool",
        clusterwide=False,
    )
