"""Unit tests for the check of ``spec.default_version`` against ``spec.supported_versions``.

A prerelease default fits a range when its numbers fit, so ``1.12.0b0`` is a
valid default for ``>=1.5,<2.0`` (#591). The check keeps its refusal message.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from styrmin_backend.services.driver.models.resources.driver import DriverSpec


def _driver_spec(*, supported_versions: str, default_version: str) -> dict[str, Any]:
    return {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "default-version"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": supported_versions,
            "default_version": default_version,
            "info": {"description": "Default version fixture"},
            "helm": {"main": {"location": "./src/helm", "version": "0.1.0"}},
        },
    }


def test_prerelease_default_loads_when_its_numbers_fit_the_range() -> None:
    spec = DriverSpec.model_validate(
        _driver_spec(supported_versions=">=1.5,<2.0", default_version="1.12.0b0")
    ).spec

    assert spec.default_version == "1.12.0b0"


def test_prerelease_default_below_the_lower_bound_is_refused_with_the_same_message() -> (
    None
):
    with pytest.raises(ValidationError) as excinfo:
        DriverSpec.model_validate(
            _driver_spec(
                supported_versions=">=1.12.0,<1.13", default_version="1.12.0b0"
            )
        )

    assert (
        "default_version '1.12.0b0' does not satisfy supported_versions '>=1.12.0,<1.13'"
        in str(excinfo.value)
    )


def test_stable_default_inside_the_range_loads() -> None:
    spec = DriverSpec.model_validate(
        _driver_spec(supported_versions=">=1.5,<2.0", default_version="1.9.0")
    ).spec

    assert spec.default_version == "1.9.0"


def test_stable_default_outside_the_range_is_refused() -> None:
    with pytest.raises(ValidationError) as excinfo:
        DriverSpec.model_validate(
            _driver_spec(supported_versions=">=1.5,<2.0", default_version="2.0.0")
        )

    assert (
        "default_version '2.0.0' does not satisfy supported_versions '>=1.5,<2.0'"
        in str(excinfo.value)
    )
