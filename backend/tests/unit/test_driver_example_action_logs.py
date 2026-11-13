"""The actions of the example drivers log no secret of the context (#573).

The Infrahub drivers logged ``f"Context: {context}"`` in ``upgrade``,
``pre_setup`` and ``post_setup``. The line held the values template, with the
Prefect database password and the Erlang cookie, and every env var value.
"""

from __future__ import annotations

import importlib.util
import io
import logging
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest
from tests.helpers.secret_context import TEMPLATE_SECRETS, secret_context

_EXAMPLES = Path(__file__).resolve().parents[3] / "driver" / "examples"
_DRIVERS = sorted(path.parent.name for path in _EXAMPLES.glob("*/actions.py"))
_SECRETS = (
    "FAKE573-env-pw",
    "FAKE573-plain-value",
    "FAKE573-param-pw",
    *TEMPLATE_SECRETS,
)


def _load_actions(driver: str) -> ModuleType:
    path = _EXAMPLES / driver / "actions.py"
    spec = importlib.util.spec_from_file_location(f"_actions_log_{driver}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_actions(module: ModuleType) -> str:
    """Run every action of ``module`` that takes a context; return what they logged."""
    stream = io.StringIO()
    run_logger = logging.getLogger(f"test.actions.{module.__name__}")
    run_logger.addHandler(logging.StreamHandler(stream))
    run_logger.setLevel(logging.DEBUG)
    run_logger.propagate = False
    context = secret_context()
    patches = [patch.object(module, "get_run_logger", return_value=run_logger)]
    for name in (
        "stop_components",
        "start_components",
        "upgrade_deployment_version",
        "execute_commands",
    ):
        if hasattr(module, name):
            patches.append(patch.object(module, name, AsyncMock()))
    if hasattr(module, "get_component_images"):
        patches.append(
            patch.object(
                module, "get_component_images", AsyncMock(return_value=["app:1.0"])
            )
        )
    for item in patches:
        item.start()
    try:
        for name in ("upgrade", "pre_setup", "post_setup"):
            action = getattr(module, name, None)
            if action is None:
                continue
            if name == "upgrade":
                result = action.fn(context=context, target_version="1.12.0")
            else:
                result = action.fn(context=context)
            if hasattr(result, "__await__"):
                await result
    finally:
        for item in patches:
            item.stop()
    return stream.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["infrahub", "infrahub-enterprise"])
async def test_infrahub_actions_log_the_deployment_not_the_secrets(driver: str) -> None:
    text = await _run_actions(_load_actions(driver))

    assert "Deployment " in text
    for secret in _SECRETS:
        assert secret not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", _DRIVERS)
async def test_no_example_action_logs_a_secret_of_the_context(driver: str) -> None:
    text = await _run_actions(_load_actions(driver))

    for secret in _SECRETS:
        assert secret not in text
