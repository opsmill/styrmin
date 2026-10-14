"""A driver file with the removed ``spec.container_overrides`` block fails to load (022 / FR-006).

The block gets no special handling: ``Specification`` forbids extra keys, so the loader
rejects it exactly as it rejects any other unknown key under ``spec``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.loaders import get_local_driver_loader

CONTAINER_OVERRIDES_BLOCK = [
    {
        "component": "server",
        "container": "simple-app",
        "command": True,
        "args": True,
        "description": "Override the server entrypoint",
    }
]


def _driver_spec(**extra_spec_keys: Any) -> dict[str, Any]:
    return {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "simple-app"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": ">=0.1,<1.0",
            "info": {"description": "Removed block fixture"},
            "helm": {"main": {"location": "./src/helm", "version": "0.1.0"}},
            "components": {
                "server": {
                    "identifier": {"label": {"app.kubernetes.io/name": "simple-app"}},
                    "container": "simple-app",
                },
            },
            **extra_spec_keys,
        },
    }


def _load_failure(tmp_path: Path, spec: dict[str, Any]) -> DriverLoadingError:
    (tmp_path / "driver.styrmin.yml").write_text(yaml.safe_dump(spec))
    (tmp_path / "values.j2.yml").write_text("{}\n")
    with pytest.raises(DriverLoadingError) as exc_info:
        get_local_driver_loader(path=str(tmp_path)).load_driver()
    return exc_info.value


def _pydantic_errors(error: DriverLoadingError) -> list[dict[str, Any]]:
    # DriverLoadingError <- DeserializationError <- pydantic ValidationError
    cause = error.__cause__.__cause__ if error.__cause__ else None
    assert isinstance(cause, PydanticValidationError)
    return [
        {"type": e["type"], "loc": e["loc"]} for e in cause.errors(include_url=False)
    ]


def test_driver_without_the_block_loads(tmp_path: Path) -> None:
    (tmp_path / "driver.styrmin.yml").write_text(yaml.safe_dump(_driver_spec()))
    (tmp_path / "values.j2.yml").write_text("{}\n")

    driver = get_local_driver_loader(path=str(tmp_path)).load_driver()

    assert driver.driver_spec.spec.components is not None  # type: ignore[union-attr]


def test_container_overrides_block_fails_with_extra_forbidden(tmp_path: Path) -> None:
    error = _load_failure(
        tmp_path, _driver_spec(container_overrides=CONTAINER_OVERRIDES_BLOCK)
    )

    assert _pydantic_errors(error) == [
        {"type": "extra_forbidden", "loc": ("spec", "container_overrides")}
    ]
    assert "spec.container_overrides: Extra inputs are not permitted" in str(error)


def test_container_overrides_block_fails_like_any_unknown_spec_key(
    tmp_path: Path,
) -> None:
    removed_dir = tmp_path / "removed"
    unknown_dir = tmp_path / "unknown"
    removed_dir.mkdir()
    unknown_dir.mkdir()

    removed = _load_failure(
        removed_dir, _driver_spec(container_overrides=CONTAINER_OVERRIDES_BLOCK)
    )
    unknown = _load_failure(
        unknown_dir, _driver_spec(not_a_spec_key=CONTAINER_OVERRIDES_BLOCK)
    )

    assert type(removed) is type(unknown)
    assert type(removed.__cause__) is type(unknown.__cause__)
    assert [e["type"] for e in _pydantic_errors(removed)] == [
        e["type"] for e in _pydantic_errors(unknown)
    ]
    assert str(removed) == str(unknown).replace("not_a_spec_key", "container_overrides")
