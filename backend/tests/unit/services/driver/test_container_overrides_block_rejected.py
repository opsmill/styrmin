"""A driver file with the removed ``spec.container_overrides`` block fails to load (022 / FR-006).

The error names the removed block and links the migration guide, unlike the generic
``extra_forbidden`` error of any other unknown key under ``spec``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.exceptions import CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL

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


def test_container_overrides_block_fails_with_the_migration_guide(
    tmp_path: Path,
) -> None:
    error = _load_failure(
        tmp_path, _driver_spec(container_overrides=CONTAINER_OVERRIDES_BLOCK)
    )

    assert _pydantic_errors(error) == [{"type": "removed_key", "loc": ("spec",)}]
    assert "spec.container_overrides was removed" in str(error)
    assert CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL in str(error)


def test_container_overrides_block_fails_even_when_empty(tmp_path: Path) -> None:
    error = _load_failure(tmp_path, _driver_spec(container_overrides=None))

    assert _pydantic_errors(error) == [{"type": "removed_key", "loc": ("spec",)}]


def test_other_unknown_spec_keys_keep_the_generic_error(tmp_path: Path) -> None:
    error = _load_failure(
        tmp_path, _driver_spec(not_a_spec_key=CONTAINER_OVERRIDES_BLOCK)
    )

    assert _pydantic_errors(error) == [
        {"type": "extra_forbidden", "loc": ("spec", "not_a_spec_key")}
    ]
    assert CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL not in str(error)
