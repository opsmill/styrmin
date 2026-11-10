"""Unit tests of the shared range check ``version_fits_range`` (#591).

A prerelease fits a range when its numbers fit, whether or not the range names
a prerelease. The rows of ``BOUNDARY_CASES`` are the boundary table of
``specs/032-prerelease-version-range/data-model.md``. Other tests import the
table so that they cannot drift from it.
"""

from __future__ import annotations

import pytest
from packaging.specifiers import InvalidSpecifier
from packaging.version import Version

from styrmin_backend.services.version_range import version_fits_range

# (range, version, fits)
BOUNDARY_CASES: list[tuple[str, str, bool]] = [
    # A prerelease whose numbers fit the range fits, in every spelling.
    (">=1.5,<2.0", "1.12.0b0", True),
    (">=1.5,<2.0", "1.9.0rc1", True),
    (">=1.5,<2.0", "1.12.0.dev3", True),
    (">=1.5,<2.0", "1.12.0-beta.1", True),
    (">=1.5,<2.0", "1.12.0.b0", True),
    (">=1.5,<2.0", "1.12.0_rc1", True),
    (">=1.5,<2.0", "1.12.0", True),
    # A prerelease below the lower bound or at the exclusive upper bound does not fit.
    (">=1.5,<2.0", "2.0.0b1", False),
    (">=1.5,<2.0", "2.0.0rc1", False),
    (">=1.5,<2.0", "1.5.0a1", False),
    (">=1.5,<2.0", "1.5.0.dev1", False),
    (">=1.5,<2.0", "1.4.0rc1", False),
    # A prerelease of the lower bound is below that bound.
    (">=1.12.0,<1.13", "1.12.0b0", False),
    (">=1.12.0,<1.13", "1.9.0rc1", False),
    (">=1.12.0,<1.13", "1.12.0.dev3", False),
    # A range that names a prerelease keeps accepting it.
    (">=1.12.0b0,<1.13", "1.12.0b0", True),
    (">=1.12.0b0,<1.13", "1.12.0", True),
    # An exact clause on the final version does not accept its prerelease.
    ("==1.12.0", "1.12.0b0", False),
    # A != clause excludes only the version it names.
    ("!=1.12.0b0", "1.12.0b1", True),
]

# Stable versions keep the verdict they had before #591 (FR-007).
STABLE_CASES: list[tuple[str, str, bool]] = [
    (">=1.5,<2.0", "1.9.0", True),
    (">=1.5,<2.0", "2.0.0", False),
]


@pytest.mark.parametrize(("supported", "version", "fits"), BOUNDARY_CASES)
def test_boundary_table(supported: str, version: str, fits: bool) -> None:
    assert version_fits_range(Version(version), supported) is fits


@pytest.mark.parametrize(("supported", "version", "fits"), STABLE_CASES)
def test_stable_versions_keep_their_verdict(
    supported: str, version: str, fits: bool
) -> None:
    assert version_fits_range(Version(version), supported) is fits


def test_invalid_range_text_raises() -> None:
    with pytest.raises(InvalidSpecifier):
        version_fits_range(Version("1.0.0"), "not a range")
