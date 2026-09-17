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
    _resolve_latest_matching_version,
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
