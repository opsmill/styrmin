"""Unit tests for the in-repo driver ``upgrade`` actions (018-component-image-overrides FR-012).

The actions take ``images[0]`` (the component container's image, see ``get_component_images``)
instead of matching an image-name substring, and rebuild its tag for the target version.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_EXAMPLES = Path(__file__).resolve().parents[3] / "driver" / "examples"
_DRIVERS = ["simple-app", "infrahub", "infrahub-enterprise"]
_DIGEST = "sha256:" + "a" * 64


def _load_actions(driver: str) -> ModuleType:
    path = _EXAMPLES / driver / "actions.py"
    spec = importlib.util.spec_from_file_location(f"_actions_{driver}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _job_image(driver: str, images: list[str]) -> str:
    module = _load_actions(driver)
    execute_commands = AsyncMock()
    with (
        patch.object(module, "get_run_logger", MagicMock()),
        patch.object(module, "stop_components", AsyncMock()),
        patch.object(module, "start_components", AsyncMock()),
        patch.object(module, "upgrade_deployment_version", AsyncMock()),
        patch.object(module, "get_component_images", AsyncMock(return_value=images)),
        patch.object(module, "execute_commands", execute_commands),
    ):
        await module.upgrade.fn(context=MagicMock(), target_version="0.2.0")
    execute_commands.assert_awaited_once()
    return execute_commands.await_args.kwargs["image"]


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", _DRIVERS)
@pytest.mark.parametrize(
    ("first_image", "expected"),
    [
        ("simple-app:0.1.0", "simple-app:0.2.0"),
        (
            "registry.example/acme/simple-app-patched:0.1.0",
            "registry.example/acme/simple-app-patched:0.2.0",
        ),
        ("registry:5000/app:0.1.0", "registry:5000/app:0.2.0"),
        ("registry:5000/app", "registry:5000/app:0.2.0"),
        (f"app@{_DIGEST}", "app:0.2.0"),
        (f"app:0.1.0@{_DIGEST}", "app:0.2.0"),
        ("app", "app:0.2.0"),
    ],
    ids=[
        "tag",
        "registry-path",
        "port-and-tag",
        "port-no-tag",
        "digest",
        "tag-digest",
        "bare",
    ],
)
async def test_upgrade_job_uses_first_image_with_target_tag(
    driver: str, first_image: str, expected: str
) -> None:
    # The sidecar image contains the driver name: a substring match would pick it.
    images = [first_image, f"sidecar/{driver}-simple-app-infrahub-exporter:9.9.9"]
    assert await _job_image(driver, images) == expected
