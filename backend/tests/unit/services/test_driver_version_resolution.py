"""Unit tests for the latest-wins driver-version ordering and resolution.

The canonical ordering (``_driver_version_sort_key``) is: highest parseable
driver ``version`` string first; unparseable versions below all parseable
ones; ties broken by ``created_on`` descending, then ``id``. The resolver
(``_resolve_latest_matching_version``) applies that ordering to the driver
versions whose ``application_supported_versions`` specifier matches the
requested application version — never the implicit DB insertion order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from packaging.version import InvalidVersion

from styrmin_backend.db.models import ApplicationDriver, ApplicationDriverVersion
from styrmin_backend.services.deployment import (
    _driver_version_sort_key,
    _ensure_pin_supports_version,
    _resolve_latest_matching_version,
)
from styrmin_backend.services.exceptions import ServiceError


def _adv(
    version: str,
    *,
    supported: str = ">=0.1,<1.0",
    created_on: datetime | None = None,
) -> ApplicationDriverVersion:
    return ApplicationDriverVersion(
        id=uuid4(),
        application_driver_id=uuid4(),
        version=version,
        application_supported_versions=supported,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        created_on=created_on,
    )


def _driver(versions: list[ApplicationDriverVersion]) -> ApplicationDriver:
    driver = ApplicationDriver(id=uuid4(), name="test-driver")
    driver.versions = versions
    return driver


_T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T2 = datetime(2026, 2, 1, tzinfo=timezone.utc)


class TestDriverVersionSortKey:
    def test_higher_version_wins_regardless_of_load_time(self) -> None:
        older_but_higher = _adv("2", created_on=_T1)
        newer_but_lower = _adv("1", created_on=_T2)
        winner = max([newer_but_lower, older_but_higher], key=_driver_version_sort_key)
        assert winner is older_but_higher

    def test_parseable_version_beats_unparseable(self) -> None:
        unparseable = _adv("not-a-version", created_on=_T2)
        parseable = _adv("0.0.1", created_on=_T1)
        winner = max([unparseable, parseable], key=_driver_version_sort_key)
        assert winner is parseable

    def test_equal_version_tie_breaks_on_created_on(self) -> None:
        older = _adv("1", created_on=_T1)
        newer = _adv("1", created_on=_T2)
        winner = max([older, newer], key=_driver_version_sort_key)
        assert winner is newer

    def test_none_created_on_sorts_oldest(self) -> None:
        unset = _adv("1", created_on=None)
        dated = _adv("1", created_on=_T1)
        winner = max([unset, dated], key=_driver_version_sort_key)
        assert winner is dated

    def test_total_order_over_mixed_rows(self) -> None:
        rows = [
            _adv("not-a-version", created_on=_T2),
            _adv("1", created_on=None),
            _adv("1", created_on=_T1),
            _adv("2", created_on=_T1),
        ]
        ranked = sorted(rows, key=_driver_version_sort_key, reverse=True)
        assert [r.version for r in ranked] == ["2", "1", "1", "not-a-version"]
        # Equal-version rows: dated beats undated.
        assert ranked[1].created_on == _T1


class TestResolveLatestMatchingVersion:
    def test_picks_latest_among_overlapping_matches(self) -> None:
        v1 = _adv("1", supported=">=0.1,<1.0", created_on=_T1)
        v2 = _adv("2", supported=">=0.1,<1.0", created_on=_T2)
        # Insertion order deliberately puts the older row first — the old
        # first-match behavior would have returned v1.
        driver = _driver([v1, v2])
        assert _resolve_latest_matching_version(driver, "0.5.0") is v2

    def test_ignores_non_matching_versions(self) -> None:
        matching = _adv("1", supported=">=0.1,<1.0", created_on=_T1)
        higher_but_non_matching = _adv("2", supported=">=2.0,<3.0", created_on=_T2)
        driver = _driver([matching, higher_but_non_matching])
        assert _resolve_latest_matching_version(driver, "0.5.0") is matching

    def test_returns_none_when_nothing_matches(self) -> None:
        driver = _driver([_adv("1", supported=">=2.0,<3.0")])
        assert _resolve_latest_matching_version(driver, "0.5.0") is None

    def test_same_version_string_tie_breaks_on_load_time(self) -> None:
        # Two builds of driver version "1" (e.g. local reloads with distinct
        # fingerprints) — the most recently loaded one wins.
        first_build = _adv("1", supported=">=0.1,<1.0", created_on=_T1)
        second_build = _adv("1", supported=">=0.1,<1.0", created_on=_T2)
        driver = _driver([first_build, second_build])
        assert _resolve_latest_matching_version(driver, "0.5.0") is second_build

    @pytest.mark.parametrize(
        "application_version", ["1.12.0b0", "1.12.0-beta.1", "1.12.0.b0"]
    )
    def test_prerelease_fitting_the_numbers_of_the_range_resolves(
        self, application_version: str
    ) -> None:
        """#591: a range that names no prerelease still accepts one that fits."""
        driver_version = _adv("1", supported=">=1.5,<2.0")
        driver = _driver([driver_version])

        assert _resolve_latest_matching_version(driver, application_version) is (
            driver_version
        )

    def test_prerelease_of_the_excluded_upper_bound_does_not_resolve(self) -> None:
        driver = _driver([_adv("1", supported=">=1.5,<2.0")])

        assert _resolve_latest_matching_version(driver, "2.0.0b1") is None

    def test_prerelease_below_the_lower_bound_does_not_resolve(self) -> None:
        driver = _driver([_adv("1", supported=">=1.12.0,<1.13")])

        assert _resolve_latest_matching_version(driver, "1.12.0b0") is None

    @pytest.mark.parametrize("insertion_order", ["lower-first", "higher-first"])
    def test_latest_wins_among_overlapping_ranges_for_a_prerelease(
        self, insertion_order: str
    ) -> None:
        standard = _adv("1", supported=">=1.5,<2.0", created_on=_T1)
        naming_a_prerelease = _adv("2", supported=">=1.12.0b0,<1.13", created_on=_T1)
        versions = [standard, naming_a_prerelease]
        if insertion_order == "higher-first":
            versions.reverse()
        driver = _driver(versions)

        assert _resolve_latest_matching_version(driver, "1.12.0b0") is (
            naming_a_prerelease
        )


class TestNonPep440VersionBehaviour:
    """Characterization test for FR-006 of #591: a version that is not PEP 440.

    ``latest`` and ``develop`` are not PEP 440 versions. Both service functions
    parse the requested version with ``packaging.version.Version`` before they
    look at any range, so both raise ``packaging.version.InvalidVersion`` from
    the service function itself. This was observed on the code before #591
    changed anything (``uv run python``, ``packaging`` 25.0): the same
    exception type and the message ``Invalid version: '<text>'``, with and
    without driver versions on the driver.

    How the GraphQL layer reports it (read in ``api/errors.py``, not run through
    a GraphQL request): ``InvalidVersion`` is a ``ValueError``, not a
    ``ServiceError``, and the mutations ``deployApplication`` and
    ``updateDeploymentVersion`` in ``api/schema/mutation.py`` do not catch it.
    ``StructuredErrorExtension`` therefore masks it as the message
    ``An internal error occurred`` with ``extensions.code`` ``INTERNAL_ERROR``.

    This outcome must not change with #591. The test must pass before and
    after the change.
    """

    @pytest.mark.parametrize("version", ["latest", "develop"])
    def test_resolver_raises_invalid_version_from_the_service_function(
        self, version: str
    ) -> None:
        driver = _driver([_adv("1")])

        with pytest.raises(InvalidVersion, match=f"Invalid version: '{version}'"):
            _resolve_latest_matching_version(driver, version)

    @pytest.mark.parametrize("version", ["latest", "develop"])
    def test_pin_check_raises_invalid_version_from_the_service_function(
        self, version: str
    ) -> None:
        with pytest.raises(InvalidVersion, match=f"Invalid version: '{version}'"):
            _ensure_pin_supports_version(_adv("1"), version)

    def test_the_exception_is_not_a_service_error(self) -> None:
        # This is why the GraphQL layer masks it as INTERNAL_ERROR.
        assert issubclass(InvalidVersion, ValueError)
        assert not issubclass(InvalidVersion, ServiceError)
