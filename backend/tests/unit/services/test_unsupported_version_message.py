"""The refusal of an unsupported application version says why and lists the ranges (#591).

A driver version's ``application_supported_versions`` range matches a
prerelease (``1.12.0b0``) only if the range itself names a prerelease. Styrmin
refused such a request with "Version 1.12.0b0 is not supported by the
application driver infrahub", which names neither the reason nor the ranges.

Three places refuse a version: creating a deployment, upgrading a deployment
and pinning a driver version. They share one message:

* a prerelease that some range would accept if prereleases were allowed gets
  the prerelease explanation and the supported ranges;
* any other refusal gets the supported ranges and no prerelease explanation.
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
EXPLANATION = (
    "a range matches a prerelease only if one of its clauses names a prerelease "
    "(a != clause does not count)"
)


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


class TestPrereleaseRefusedBecauseNoRangeNamesOne:
    """A prerelease that the range would accept if prereleases were allowed."""

    @pytest.mark.anyio
    async def test_create_explains_the_prerelease_rule_and_lists_the_range(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_create(uow, environment_id, "1.5.0b0")

        assert f"Version {PRERELEASE} is not supported by the application driver" in (
            message
        )
        assert DRIVER in message
        assert f"supported ranges: {STABLE_ONLY}" in message
        assert EXPLANATION in message

    @pytest.mark.anyio
    async def test_upgrade_explains_the_prerelease_rule_and_lists_the_range(
        self,
    ) -> None:
        uow, deployment_id, _ = await _seed()

        message = await _refused_on_upgrade(uow, deployment_id, "1.5.0b0")

        assert f"Version {PRERELEASE} is not supported by the application driver" in (
            message
        )
        assert f"supported ranges: {STABLE_ONLY}" in message
        assert EXPLANATION in message

    @pytest.mark.anyio
    async def test_pin_explains_the_prerelease_rule_and_keeps_the_pinned_range(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()
        pin = uow.application_driver_versions.models[0]

        message = await _refused_on_pin(uow, environment_id, "1.5.0b0")

        assert f"Version {PRERELEASE} is not supported by driver version {pin.id}" in (
            message
        )
        assert f"(supports {STABLE_ONLY})" in message
        assert EXPLANATION in message

    @pytest.mark.anyio
    async def test_every_range_of_the_driver_is_listed_once(self) -> None:
        uow, _, environment_id = await _seed(
            extra_versions=[("2.0.0", STABLE_ONLY), ("3.0.0", ">=2.0.0,<3.0.0")]
        )

        message = await _refused_on_create(uow, environment_id, "1.5.0b0")

        assert message.count(STABLE_ONLY) == 1
        assert ">=2.0.0,<3.0.0" in message
        assert EXPLANATION in message

    @pytest.mark.anyio
    async def test_ranges_are_listed_newest_driver_version_first(self) -> None:
        # Text order would put ">=1.10" before ">=1.9"; driver version order does not.
        uow, _, environment_id = await _seed(
            extra_versions=[("2", ">=1.9,<1.10"), ("10", ">=1.10,<1.11")]
        )

        message = await _refused_on_create(uow, environment_id, "1.5.0b0")

        assert (
            f"supported ranges: >=1.10,<1.11, >=1.9,<1.10, {STABLE_ONLY}"
        ) in message

    @pytest.mark.anyio
    async def test_a_not_equal_clause_that_names_a_prerelease_does_not_count(
        self,
    ) -> None:
        uow, _, environment_id = await _seed(
            extra_versions=[("2", ">=1.0.0,!=1.5.0b0,<2.0.0")]
        )

        message = await _refused_on_create(uow, environment_id, "1.5.0b1")

        assert "!=1.5.0b0" in message
        assert EXPLANATION in message


class TestRefusalWithoutAPrereleaseExplanation:
    """Any refusal for which naming a prerelease in the range would not help."""

    @pytest.mark.anyio
    async def test_stable_version_outside_every_range_lists_the_ranges_only(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_create(uow, environment_id, "0.9.0")

        assert "Version 0.9.0 is not supported by the application driver" in message
        assert f"supported ranges: {STABLE_ONLY}" in message
        assert "prerelease" not in message

    @pytest.mark.anyio
    async def test_prerelease_outside_every_range_even_when_prereleases_are_allowed(
        self,
    ) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_create(uow, environment_id, "0.9.0b1")

        assert f"supported ranges: {STABLE_ONLY}" in message
        assert "prerelease" not in message

    @pytest.mark.anyio
    async def test_upgrade_to_a_stable_version_outside_the_range(self) -> None:
        uow, deployment_id, _ = await _seed()

        message = await _refused_on_upgrade(uow, deployment_id, "3.0.0")

        assert f"supported ranges: {STABLE_ONLY}" in message
        assert "prerelease" not in message

    @pytest.mark.anyio
    async def test_pin_to_a_stable_version_outside_the_range(self) -> None:
        uow, _, environment_id = await _seed()

        message = await _refused_on_pin(uow, environment_id, "3.0.0")

        assert f"(supports {STABLE_ONLY})" in message
        assert "prerelease" not in message


class TestPrereleaseAcceptedWhenARangeNamesOne:
    """The matching rule is unchanged: the second driver build of the issue's control."""

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
