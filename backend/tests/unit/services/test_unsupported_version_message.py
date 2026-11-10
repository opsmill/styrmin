"""The refusal of an unsupported application version names the version and lists the ranges (#591).

Three places refuse a version: creating a deployment, upgrading a deployment
and pinning a driver version.

* Creating and upgrading without a pin refuse with the version and every
  supported range of the driver, listed once, newest driver version first.
* Pinning a driver version refuses with the version, the pinned driver
  version and its range, then lists every supported range of the driver the
  same way (FR-004, SC-003).
* No message explains a prerelease rule or contains the word "prerelease"
  (FR-005), because a prerelease whose numbers fit a range is accepted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import ApplicationDriver
from styrmin_backend.services.deployment import (
    _unsupported_version_error,
    deploy_application,
    update_deployment_version,
)
from styrmin_backend.services.exceptions import InvalidVersionError
from tests.unit.services.fakes import FakeApplicationDriverRepository, FakeUnitOfWork
from tests.unit.services.test_update_deployment_noop import (
    _fake_apply_state,
    _make_uow,
    _seed_steady_state_deployment,
)

MODULE = "styrmin_backend.services.deployment"
DRIVER = "test-app"
STABLE_ONLY = ">=1.0.0,<2.0.0"
PRERELEASE_RANGE = ">=1.5.0b0,<1.6"
PRERELEASE = "1.5.0b0"
# Outside ``STABLE_ONLY``, so refused whatever the rule for prereleases is.
PRERELEASE_ABOVE_THE_RANGE = "2.0.0b1"


async def _seed(
    *, extra_versions: list[tuple[str, str]] | None = None
) -> tuple[FakeUnitOfWork, UUID, UUID]:
    """A uow with one running deployment bound to the driver version ``STABLE_ONLY``."""
    uow = _make_uow()
    environment_id = uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=uuid4(),
        environment_id=environment_id,
        supported_versions=STABLE_ONLY,
        extra_versions=extra_versions,
    )
    # ``deploy_application`` looks the driver up by name, which the seed's
    # repository does not offer.
    drivers = FakeApplicationDriverRepository()
    drivers.models = list(uow.application_drivers.models)
    uow.application_drivers = drivers
    return uow, deployment.id, environment_id


async def _refused_on_create(
    uow: FakeUnitOfWork, environment_id: UUID, version: str
) -> str:
    with pytest.raises(InvalidVersionError) as raised:
        await deploy_application(
            driver_name=DRIVER,
            version=version,
            environment_id=environment_id,
            uow=uow,
            created_by_user_id=uuid4(),
        )
    return str(raised.value)


async def _refused_on_upgrade(
    uow: FakeUnitOfWork, deployment_id: UUID, version: str
) -> str:
    with pytest.raises(InvalidVersionError) as raised:
        await update_deployment_version(
            deployment_id=deployment_id, version=version, uow=uow
        )
    return str(raised.value)


async def _refused_on_pin(
    uow: FakeUnitOfWork, environment_id: UUID, version: str
) -> str:
    pin = uow.application_driver_versions.models[0]
    with pytest.raises(InvalidVersionError) as raised:
        await deploy_application(
            driver_name=DRIVER,
            version=version,
            environment_id=environment_id,
            uow=uow,
            created_by_user_id=uuid4(),
            driver_version_id=pin.id,
        )
    return str(raised.value)


class TestRefusalListsTheVersionAndTheRanges:
    @pytest.mark.anyio
    async def test_create_names_the_version_and_lists_the_range(self) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_create(uow, environment_id, "3.0.0")

        assert "Version 3.0.0 is not supported by the application driver" in message
        assert DRIVER in message
        assert f"supported ranges: {STABLE_ONLY}" in message

    @pytest.mark.anyio
    async def test_upgrade_names_the_version_and_lists_the_range(self) -> None:
        uow, deployment_id, _ = await _seed()

        message = await _refused_on_upgrade(uow, deployment_id, "3.0.0")

        assert "Version 3.0.0 is not supported by the application driver" in message
        assert f"supported ranges: {STABLE_ONLY}" in message

    @pytest.mark.anyio
    async def test_pin_names_the_version_the_pinned_range_and_the_driver_ranges(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()
        pin = uow.application_driver_versions.models[0]

        message = await _refused_on_pin(uow, environment_id, "3.0.0")

        assert f"Version 3.0.0 is not supported by driver version {pin.id}" in message
        assert f"(supports {STABLE_ONLY})." in message
        assert (
            f"Supported ranges of the application driver {DRIVER}: {STABLE_ONLY}."
        ) in message

    @pytest.mark.anyio
    async def test_every_range_of_the_driver_is_listed_once(self) -> None:
        uow, _, environment_id = await _seed(
            extra_versions=[("2.0.0", STABLE_ONLY), ("3.0.0", ">=2.0.0,<3.0.0")]
        )

        message = await _refused_on_create(uow, environment_id, "4.0.0")

        assert message.count(STABLE_ONLY) == 1
        assert ">=2.0.0,<3.0.0" in message

    @pytest.mark.anyio
    async def test_ranges_are_listed_newest_driver_version_first(self) -> None:
        # The order is the driver version order, newest first: 10, 2, 1.0.0.
        # Not the insertion order (1.0.0, 2, 10), and not a sort of the driver
        # version strings, which would put "2" before "10". Ascending text order
        # of the ranges would put ">=1.10" first too, so this does not tell
        # those two apart.
        uow, _, environment_id = await _seed(
            extra_versions=[("2", ">=1.9,<1.10"), ("10", ">=1.10,<1.11")]
        )

        message = await _refused_on_create(uow, environment_id, "4.0.0")

        assert (
            f"supported ranges: >=1.10,<1.11, >=1.9,<1.10, {STABLE_ONLY}"
        ) in message


MANY_RANGES = [("2", ">=1.9,<1.10"), ("10", ">=1.10,<1.11")]
LISTED_RANGES = f">=1.10,<1.11, >=1.9,<1.10, {STABLE_ONLY}"


class TestRefusalMessagesFollowTheContract:
    """The exact texts of messages 1 and 2 of contracts/refusal-messages.md."""

    @pytest.mark.anyio
    async def test_message_1_for_an_unpinned_request_of_a_prerelease(self) -> None:
        uow, _, environment_id = await _seed(extra_versions=MANY_RANGES)

        message = await _refused_on_create(
            uow, environment_id, PRERELEASE_ABOVE_THE_RANGE
        )

        assert message == (
            f"Version {PRERELEASE_ABOVE_THE_RANGE} is not supported by the "
            f"application driver {DRIVER} (supported ranges: {LISTED_RANGES})."
        )

    @pytest.mark.anyio
    async def test_message_1_lists_every_range_once_on_an_upgrade(self) -> None:
        # Driver version "11" repeats the range of driver version "1.0.0".
        uow, deployment_id, _ = await _seed(
            extra_versions=[*MANY_RANGES, ("11", STABLE_ONLY)]
        )

        message = await _refused_on_upgrade(
            uow, deployment_id, PRERELEASE_ABOVE_THE_RANGE
        )

        assert message == (
            f"Version {PRERELEASE_ABOVE_THE_RANGE} is not supported by the "
            f"application driver {DRIVER} (supported ranges: "
            f"{STABLE_ONLY}, >=1.10,<1.11, >=1.9,<1.10)."
        )
        assert message.count(STABLE_ONLY) == 1

    @pytest.mark.anyio
    async def test_message_2_names_the_pin_and_lists_every_range_of_the_driver(
        self,
    ) -> None:
        uow, _, environment_id = await _seed(extra_versions=MANY_RANGES)
        pin = uow.application_driver_versions.models[0]

        message = await _refused_on_pin(uow, environment_id, PRERELEASE_ABOVE_THE_RANGE)

        assert message == (
            f"Version {PRERELEASE_ABOVE_THE_RANGE} is not supported by driver "
            f"version {pin.id} (supports {pin.application_supported_versions}). "
            f"Supported ranges of the application driver {DRIVER}: {LISTED_RANGES}."
        )

    @pytest.mark.anyio
    async def test_message_2_on_an_upgrade_lists_every_range_of_the_driver(
        self,
    ) -> None:
        uow, deployment_id, _ = await _seed(extra_versions=MANY_RANGES)
        pin = uow.application_driver_versions.models[0]

        with pytest.raises(InvalidVersionError) as raised:
            await update_deployment_version(
                deployment_id=deployment_id,
                version=PRERELEASE_ABOVE_THE_RANGE,
                uow=uow,
                driver_version_id=pin.id,
            )

        assert str(raised.value) == (
            f"Version {PRERELEASE_ABOVE_THE_RANGE} is not supported by driver "
            f"version {pin.id} (supports {pin.application_supported_versions}). "
            f"Supported ranges of the application driver {DRIVER}: {LISTED_RANGES}."
        )

    @pytest.mark.anyio
    async def test_message_2_lists_the_one_range_of_a_driver_with_one_range(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()
        pin = uow.application_driver_versions.models[0]

        message = await _refused_on_pin(uow, environment_id, PRERELEASE_ABOVE_THE_RANGE)

        assert message.endswith(
            f"(supports {STABLE_ONLY}). "
            f"Supported ranges of the application driver {DRIVER}: {STABLE_ONLY}."
        )
        assert str(pin.id) in message


class TestADriverWithNoDriverVersions:
    """Message 1 has no parenthesis when the driver has no driver version."""

    EXPECTED = f"Version 1.0.0 is not supported by the application driver {DRIVER}."

    def test_the_message_has_no_list_of_ranges(self) -> None:
        driver = ApplicationDriver(id=uuid4(), name=DRIVER)
        driver.versions = []

        error = _unsupported_version_error(driver, "1.0.0")

        assert isinstance(error, InvalidVersionError)
        assert str(error) == self.EXPECTED

    @pytest.mark.anyio
    async def test_creating_a_deployment_refuses_with_that_message(self) -> None:
        uow = _make_uow()
        driver = ApplicationDriver(id=uuid4(), name=DRIVER)
        driver.versions = []
        drivers = FakeApplicationDriverRepository()
        drivers.models = [driver]
        uow.application_drivers = drivers

        message = await _refused_on_create(uow, uuid4(), "1.0.0")

        assert message == self.EXPECTED


def _snapshot(uow: FakeUnitOfWork) -> dict[str, list]:
    return {
        "deployments": [d.id for d in uow.deployments._deployments],
        "instances": [i.id for i in uow.instances.models],
        "tasks": [t.id for t in uow.tasks.models],
    }


class TestARefusalCreatesNothing:
    """The error is raised before anything is dispatched or stored."""

    @pytest.mark.anyio
    @patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
    @pytest.mark.parametrize("pinned", [False, True])
    async def test_create_creates_no_resource(
        self, mock_apply_state: AsyncMock, pinned: bool
    ) -> None:
        uow, _, environment_id = await _seed(extra_versions=MANY_RANGES)
        before = _snapshot(uow)

        if pinned:
            await _refused_on_pin(uow, environment_id, PRERELEASE_ABOVE_THE_RANGE)
        else:
            await _refused_on_create(uow, environment_id, PRERELEASE_ABOVE_THE_RANGE)

        assert _snapshot(uow) == before
        mock_apply_state.assert_not_called()

    @pytest.mark.anyio
    @patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
    async def test_upgrade_creates_no_resource(
        self, mock_apply_state: AsyncMock
    ) -> None:
        uow, deployment_id, _ = await _seed(extra_versions=MANY_RANGES)
        before = _snapshot(uow)

        await _refused_on_upgrade(uow, deployment_id, PRERELEASE_ABOVE_THE_RANGE)

        assert _snapshot(uow) == before
        mock_apply_state.assert_not_called()


class TestNoMessageMentionsAPrerelease:
    """FR-005: a refused prerelease gets the same message as a refused stable version."""

    @pytest.mark.anyio
    async def test_create_refusal_of_a_prerelease_lists_the_ranges_only(self) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_create(
            uow, environment_id, PRERELEASE_ABOVE_THE_RANGE
        )

        assert (
            f"Version {PRERELEASE_ABOVE_THE_RANGE} is not supported by the "
            "application driver"
        ) in message
        assert f"supported ranges: {STABLE_ONLY}" in message
        assert "prerelease" not in message.lower()

    @pytest.mark.anyio
    async def test_upgrade_refusal_of_a_prerelease_lists_the_ranges_only(self) -> None:
        uow, deployment_id, _ = await _seed()

        message = await _refused_on_upgrade(
            uow, deployment_id, PRERELEASE_ABOVE_THE_RANGE
        )

        assert f"supported ranges: {STABLE_ONLY}" in message
        assert "prerelease" not in message.lower()

    @pytest.mark.anyio
    async def test_pin_refusal_of_a_prerelease_lists_the_ranges_only(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_pin(uow, environment_id, PRERELEASE_ABOVE_THE_RANGE)

        assert f"(supports {STABLE_ONLY})." in message
        assert f"Supported ranges of the application driver {DRIVER}:" in message
        assert "prerelease" not in message.lower()

    @pytest.mark.anyio
    async def test_prerelease_below_every_range_lists_the_ranges_only(self) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_create(uow, environment_id, "0.9.0b1")

        assert f"supported ranges: {STABLE_ONLY}" in message
        assert "prerelease" not in message.lower()


class TestPrereleaseAcceptedWhenARangeNamesOne:
    """A range that names a prerelease accepts it; the newest fitting build binds."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
    async def test_an_upgrade_to_a_prerelease_is_accepted_when_a_range_names_it(
        self, mock_apply_state: AsyncMock
    ) -> None:
        mock_apply_state.side_effect = _fake_apply_state
        uow, deployment_id, _ = await _seed(
            extra_versions=[("2.0.0", PRERELEASE_RANGE)]
        )

        async with uow:
            task = await update_deployment_version(
                deployment_id=deployment_id, version=PRERELEASE, uow=uow
            )

        assert task is not None
        mock_apply_state.assert_called_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
    async def test_a_newer_build_whose_range_names_no_prerelease_binds_over_an_older_one_that_does(
        self, mock_apply_state: AsyncMock
    ) -> None:
        """#591: both ranges fit ``1.5.0b0``, so the newest driver version binds.

        On the code before #591 only the older build fit, because its range
        names a prerelease (``Version("1.5.0b0") in SpecifierSet(">=1.5.0b0,<1.6")``
        is True) and the range of the newer build does not (``in
        SpecifierSet(">=1.0.0,<2.0.0")`` is False). It picked the older build.
        This test fails on that code.
        """
        mock_apply_state.side_effect = _fake_apply_state
        uow, deployment_id, _ = await _seed(
            extra_versions=[("0.9.0", PRERELEASE_RANGE), ("2.0.0", STABLE_ONLY)]
        )
        newest_build = next(
            driver_version
            for driver_version in uow.application_driver_versions.models
            if driver_version.version == "2.0.0"
        )

        async with uow:
            task = await update_deployment_version(
                deployment_id=deployment_id, version=PRERELEASE, uow=uow
            )

        assert task is not None
        deployment = await uow.deployments.find(id=deployment_id)
        assert deployment is not None
        assert deployment.application_driver_version_id == newest_build.id
