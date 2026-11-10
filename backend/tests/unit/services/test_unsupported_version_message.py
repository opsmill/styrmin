"""The refusal of an unsupported application version names the version and lists the ranges (#591).

Three places refuse a version: creating a deployment, upgrading a deployment
and pinning a driver version.

* Creating and upgrading without a pin refuse with the version and every
  supported range of the driver, listed once, newest driver version first.
* Pinning a driver version refuses with the version and the range of the
  pinned driver version.
* No message explains a prerelease rule or contains the word "prerelease"
  (FR-005), because a prerelease whose numbers fit a range is accepted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from styrmin_backend.services.deployment import (
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
    async def test_pin_names_the_version_and_keeps_the_pinned_range(self) -> None:
        uow, _, environment_id = await _seed()
        pin = uow.application_driver_versions.models[0]

        message = await _refused_on_pin(uow, environment_id, "3.0.0")

        assert f"Version 3.0.0 is not supported by driver version {pin.id}" in message
        assert f"(supports {STABLE_ONLY})" in message

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
        # Text order would put ">=1.10" before ">=1.9"; driver version order does not.
        uow, _, environment_id = await _seed(
            extra_versions=[("2", ">=1.9,<1.10"), ("10", ">=1.10,<1.11")]
        )

        message = await _refused_on_create(uow, environment_id, "4.0.0")

        assert (
            f"supported ranges: >=1.10,<1.11, >=1.9,<1.10, {STABLE_ONLY}"
        ) in message


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
    async def test_pin_refusal_of_a_prerelease_keeps_the_pinned_range_only(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_pin(uow, environment_id, PRERELEASE_ABOVE_THE_RANGE)

        assert f"(supports {STABLE_ONLY})" in message
        assert "prerelease" not in message.lower()

    @pytest.mark.anyio
    async def test_prerelease_below_every_range_lists_the_ranges_only(self) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_create(uow, environment_id, "0.9.0b1")

        assert f"supported ranges: {STABLE_ONLY}" in message
        assert "prerelease" not in message.lower()


class TestPrereleaseAcceptedWhenARangeNamesOne:
    """A range that names a prerelease accepts it and binds that driver build."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
    async def test_a_range_that_names_a_prerelease_accepts_it_and_binds_that_build(
        self, mock_apply_state: AsyncMock
    ) -> None:
        mock_apply_state.side_effect = _fake_apply_state
        uow, deployment_id, _ = await _seed(
            extra_versions=[("2.0.0", PRERELEASE_RANGE)]
        )
        beta_build = next(
            driver_version
            for driver_version in uow.application_driver_versions.models
            if driver_version.application_supported_versions == PRERELEASE_RANGE
        )

        async with uow:
            task = await update_deployment_version(
                deployment_id=deployment_id, version=PRERELEASE, uow=uow
            )

        assert task is not None
        mock_apply_state.assert_called_once()
        deployment = await uow.deployments.find(id=deployment_id)
        assert deployment is not None
        assert deployment.application_driver_version_id == beta_build.id
