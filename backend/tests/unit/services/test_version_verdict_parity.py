"""The three places that test a version against a range give one verdict (#591, FR-002, SC-002).

The picker of a driver version (``_resolve_latest_matching_version``), the check
of a pinned driver version (``_ensure_pin_supports_version``) and the check of a
driver's ``default_version`` (the ``Specification`` model) must agree with the
shared check ``version_fits_range`` on every row of ``BOUNDARY_CASES``, which is
the boundary table of ``specs/032-prerelease-version-range/data-model.md``.
"""

from __future__ import annotations

from typing import Any

import pytest
from packaging.version import Version
from pydantic import ValidationError

from styrmin_backend.services.deployment import (
    _ensure_pin_supports_version,
    _resolve_latest_matching_version,
)
from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.exceptions import InvalidVersionError
from styrmin_backend.services.version_range import version_fits_range
from tests.unit.services.test_driver_version_resolution import _adv, _driver
from tests.unit.services.test_version_range import BOUNDARY_CASES, STABLE_CASES

ALL_CASES = BOUNDARY_CASES + STABLE_CASES


def _picker_verdict(supported: str, version: str) -> bool:
    driver_version = _adv("1", supported=supported)
    return _resolve_latest_matching_version(_driver([driver_version]), version) is (
        driver_version
    )


def _pin_verdict(supported: str, version: str) -> bool:
    pinned = _adv("1", supported=supported)
    driver = _driver([pinned])
    try:
        _ensure_pin_supports_version(pinned, driver, version)
    except InvalidVersionError:
        return False
    return True


def _default_version_verdict(supported: str, version: str) -> bool:
    spec: dict[str, Any] = {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "parity"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": supported,
            "default_version": version,
            "info": {"description": "Parity fixture"},
            "helm": {"main": {"location": "./src/helm", "version": "0.1.0"}},
        },
    }
    try:
        DriverSpec.model_validate(spec)
    except ValidationError as error:
        # Only the refusal of the default version counts as "does not fit".
        assert "does not satisfy supported_versions" in str(error), error
        return False
    return True


@pytest.mark.parametrize(("supported", "version", "fits"), ALL_CASES)
def test_the_picker_gives_the_verdict_of_the_shared_check(
    supported: str, version: str, fits: bool
) -> None:
    assert version_fits_range(Version(version), supported) is fits
    assert _picker_verdict(supported, version) is fits


@pytest.mark.parametrize(("supported", "version", "fits"), ALL_CASES)
def test_the_pin_check_gives_the_verdict_of_the_shared_check(
    supported: str, version: str, fits: bool
) -> None:
    assert version_fits_range(Version(version), supported) is fits
    assert _pin_verdict(supported, version) is fits


@pytest.mark.parametrize(("supported", "version", "fits"), ALL_CASES)
def test_the_default_version_check_gives_the_verdict_of_the_shared_check(
    supported: str, version: str, fits: bool
) -> None:
    assert version_fits_range(Version(version), supported) is fits
    assert _default_version_verdict(supported, version) is fits
