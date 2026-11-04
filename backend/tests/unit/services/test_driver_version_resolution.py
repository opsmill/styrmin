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

from styrmin_backend.db.models import ApplicationDriver, ApplicationDriverVersion
from styrmin_backend.services.deployment import (
    _driver_version_sort_key,
    _ensure_pin_supports_version,
    _parse_application_version,
    _resolve_latest_matching_version,
    _supported_ranges,
)
from styrmin_backend.services.exceptions import InvalidVersionSyntaxError


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


class TestUnparseableRequestedVersion:
    """A non-version string from the user must raise the typed syntax error
    (``VALIDATION_ERROR``) rather than leak ``packaging.version.InvalidVersion``,
    which the API would mask as an internal error (#329).
    """

    def test_resolve_latest_matching_version_raises_typed_error(self) -> None:
        driver = _driver([_adv("1.0.0", supported=">=1.0.0")])
        with pytest.raises(InvalidVersionSyntaxError, match="'tata'"):
            _resolve_latest_matching_version(driver, "tata")

    def test_ensure_pin_supports_version_raises_typed_error(self) -> None:
        pinned = _adv("1.0.0", supported=">=1.0.0")
        with pytest.raises(InvalidVersionSyntaxError, match="'tata'"):
            _ensure_pin_supports_version(pinned, "tata")

    def test_error_names_the_accepted_version_format(self) -> None:
        # An application that tags releases another way (``1.2.3-ls45``,
        # ``latest``, a commit hash) must learn which format Styrmin reads.
        with pytest.raises(InvalidVersionSyntaxError, match="PEP 440"):
            _parse_application_version("1.2.3-ls45")


# The deploy form checks the shape of the version field with
# ``APPLICATION_VERSION_PATTERN`` in ``frontend/src/lib/applicationVersion.ts``.
# That pattern must let through everything the server parses, so a value the
# server accepts is never blocked in the browser. The list below is the one in
# ``frontend/src/lib/applicationVersion.test.ts``: keep the two in step.
PEP_440_VERSIONS = [
    "1",
    "1.0",
    "1.0.0",
    "0.2.0",
    "2.0rc1",
    "1.0.post1",
    "1.0.0-beta+build.1",
    "v1.6.0",
    "V1.6.0",
    "1!1.6.0",
    "1.2.3_rc1",
    "1.2.3+build_5",
    "2026.8.5",
]

# Versions that are not PEP 440: release tags with a distribution suffix,
# date-style strings and moving tags. These cannot be a deployment's
# application version, because Styrmin compares it with the driver's range.
NON_PEP_440_VERSIONS = [
    "latest",
    "main",
    "3f2a9c1",
    "2024-10-01",
    "1.2.3-ls45",
    "7.1.0-alpine",
    "1.2.3-SNAPSHOT",
    "1.0.0-x.7.z.92",
]


class TestParseApplicationVersion:
    @pytest.mark.parametrize("version", PEP_440_VERSIONS)
    def test_parses_pep_440_versions(self, version: str) -> None:
        _parse_application_version(version)

    @pytest.mark.parametrize("version", NON_PEP_440_VERSIONS)
    def test_rejects_non_pep_440_versions_with_typed_error(self, version: str) -> None:
        with pytest.raises(InvalidVersionSyntaxError, match=repr(version)):
            _parse_application_version(version)


class TestSupportedRanges:
    """The ranges quoted in a "not supported" message."""

    def test_lists_each_range_once_newest_driver_version_first(self) -> None:
        driver = _driver(
            [
                _adv("1", supported=">=0.1,<1.0"),
                _adv("3", supported=">=2.0,<3.0"),
                _adv("2", supported=">=1.0,<2.0"),
                _adv("4", supported=">=2.0,<3.0"),
            ]
        )
        # ";" separates ranges, because a range itself holds commas.
        assert _supported_ranges(driver) == ">=2.0,<3.0; >=1.0,<2.0; >=0.1,<1.0"

    def test_without_driver_versions(self) -> None:
        assert _supported_ranges(_driver([])) == "none"
