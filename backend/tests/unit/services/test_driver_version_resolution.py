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
    _resolve_latest_matching_version,
)


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


class TestPrereleaseMatching:
    """A range matches a prerelease only if the range names one (PEP 440, #591).

    The rows of the three ranges are the table of
    ``docs/docs/drivers/creating-a-driver.md``. The last two rows are the
    clauses that the table does not show: ``!=`` does not count, a bound does.
    """

    @pytest.mark.parametrize(
        ("supported", "application_version", "matches"),
        [
            (">=1.5,<2.0", "1.12.0b0", False),
            (">=1.5,<2.0", "1.12.0rc1", False),
            (">=1.5,<2.0", "1.12.0.dev1", False),
            (">=1.5,<2.0", "1.12.0", True),
            (">=1.5,<2.0", "1.9.0rc1", False),
            (">=1.12.0b0,<1.13", "1.12.0b0", True),
            (">=1.12.0b0,<1.13", "1.12.0", True),
            (">=1.12.0b0,<1.13", "1.9.0rc1", False),
            (">=1.5.0b0,<2.0", "1.12.0b0", True),
            (">=1.5.0b0,<2.0", "1.12.0", True),
            (">=1.5.0b0,<2.0", "1.9.0rc1", True),
            (">=1.5.0b0,<2.0", "1.6.0.dev1", True),
            (">=1.5,!=1.12.0b0,<2.0", "1.12.0b1", False),
            (">=1.5,<2.0b0", "1.12.0b1", True),
        ],
    )
    def test_range_matches_a_prerelease_only_if_it_names_one(
        self, supported: str, application_version: str, matches: bool
    ) -> None:
        driver = _driver([_adv("1", supported=supported)])

        resolved = _resolve_latest_matching_version(driver, application_version)

        assert (resolved is not None) is matches
