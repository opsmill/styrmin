"""Unit tests for the retired-parameter rule (023 T037, research D-007, FR-010).

On a driver version change, a parameter the current version declares and the target does not
is dropped when its value equals the current default (same type and value), and otherwise
raises ``RETIRED_PARAMETER_VALUE``. ``update_deployment_version`` applies the rule to the merged
parameter map before ``validate_parameter_values`` runs against the target version.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from loguru import logger

from styrmin_backend.db.models import ApplicationDriver, ApplicationDriverVersion
from styrmin_backend.domain.models import Deployment
from styrmin_backend.services.deployment import update_deployment_version
from styrmin_backend.services.driver.models.resources.parameters import (
    DriverParameterDefinition,
    DriverParameterKind,
)
from styrmin_backend.services.exceptions import ServiceError
from styrmin_backend.services.parameters import validate_parameter_values
from styrmin_backend.services.parameters.exceptions import RetiredParameterValueError
from styrmin_backend.services.parameters.retired import drop_retired_parameters
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)

CHECKED_AGAINST = "driver generic version 2 (application version 1.0.0)"
MIGRATION_GUIDE_URL = (
    "https://docs.styrmin.app/docs/drivers/migrating-replica-parameters"
)
RETIRED_PARAMETERS_GUIDE_URL = (
    "https://docs.styrmin.app/docs/drivers/changing-driver-versions"
)


def _integer(name: str, default: int | None) -> DriverParameterDefinition:
    return DriverParameterDefinition(
        name=name, label=name, kind=DriverParameterKind.INTEGER, default=default
    )


# ``p`` is retired by the target; ``q`` is declared by both versions.
CURRENT = [_integer("p", 5), _integer("q", 1)]
TARGET = [_integer("q", 1)]


def _drop(values: dict[str, Any]) -> dict[str, Any]:
    return drop_retired_parameters(
        values,
        current_definitions=CURRENT,
        target_definitions=TARGET,
        checked_against=CHECKED_AGAINST,
    )


def test_retired_value_equal_to_current_default_is_dropped() -> None:
    assert _drop({"p": 5, "q": 1}) == {"q": 1}


def test_dropped_retired_value_is_logged_with_the_deployment() -> None:
    messages: list[str] = []
    sink = logger.add(messages.append, level="INFO", format="{message}")
    try:
        drop_retired_parameters(
            {"p": 5},
            current_definitions=CURRENT,
            target_definitions=TARGET,
            checked_against=CHECKED_AGAINST,
            deployment_id="dep-1",
        )
    finally:
        logger.remove(sink)

    assert any(
        "Deployment dep-1: dropping retired parameter p" in m for m in messages
    ), messages


def test_changed_retired_value_is_rejected_with_metadata() -> None:
    with pytest.raises(RetiredParameterValueError) as excinfo:
        _drop({"p": 7, "q": 1})

    error = excinfo.value
    assert error.error_code == "RETIRED_PARAMETER_VALUE"
    assert error.error_metadata == {
        "parameter_name": "p",
        "value": 7,
        "default": 5,
        "checked_against": CHECKED_AGAINST,
    }
    message = str(error)
    assert "'p'" in message
    assert CHECKED_AGAINST in message
    assert "7" in message and "5" in message
    assert "replica override" in message
    assert MIGRATION_GUIDE_URL in message
    assert RETIRED_PARAMETERS_GUIDE_URL in message


@pytest.mark.parametrize(
    "value",
    ["1", 1.0, True],
    ids=["string", "float", "bool"],
)
def test_value_of_another_type_does_not_match_the_default(value: Any) -> None:
    """Strict equality: ``"1"``, ``1.0`` and ``True`` equal ``1`` in Python, not here."""
    definitions = [_integer("replicas_server", 1)]

    with pytest.raises(RetiredParameterValueError) as excinfo:
        drop_retired_parameters(
            {"replicas_server": value},
            current_definitions=definitions,
            target_definitions=[],
            checked_against=CHECKED_AGAINST,
        )

    assert excinfo.value.error_metadata["value"] is value
    assert excinfo.value.error_metadata["default"] == 1


def test_key_declared_by_both_versions_is_kept_whatever_its_value() -> None:
    assert _drop({"p": 5, "q": 42}) == {"q": 42}


def test_key_declared_by_neither_version_is_left_for_validate_parameter_values() -> (
    None
):
    kept = _drop({"p": 5, "typo": 3})

    assert kept == {"typo": 3}
    with pytest.raises(ServiceError, match="Unknown parameter: 'typo'") as excinfo:
        validate_parameter_values(TARGET, kept)
    assert RETIRED_PARAMETERS_GUIDE_URL in str(excinfo.value)


def test_absent_retired_key_is_not_an_error() -> None:
    assert _drop({"q": 1}) == {"q": 1}


def test_input_map_is_not_mutated() -> None:
    values = {"p": 5, "q": 1}

    _drop(values)

    assert values == {"p": 5, "q": 1}


def test_first_changed_retired_key_by_name_is_reported() -> None:
    definitions = [_integer("replicas_task_worker", 2), _integer("replicas_server", 1)]

    with pytest.raises(RetiredParameterValueError) as excinfo:
        drop_retired_parameters(
            {"replicas_task_worker": 4, "replicas_server": 3},
            current_definitions=definitions,
            target_definitions=[],
            checked_against=CHECKED_AGAINST,
        )

    assert excinfo.value.error_metadata["parameter_name"] == "replicas_server"


# ---------------------------------------------------------------------------
# update_deployment_version applies the rule to the merged parameter map
# ---------------------------------------------------------------------------


class _StopAfterRule(Exception):
    """Raised by the patched ``validate_parameter_values`` to capture what reached it."""

    def __init__(self, values: dict[str, Any] | None) -> None:
        super().__init__()
        self.values = values


def _stop(definitions: Any, values: dict[str, Any] | None) -> dict[str, Any]:
    raise _StopAfterRule(values)


def _parameter_dicts(definitions: list[DriverParameterDefinition]) -> list[dict]:
    return [d.model_dump(mode="json") for d in definitions]


async def _seed(stored: dict[str, Any]) -> tuple[FakeUnitOfWork, UUID, UUID, UUID]:
    """Seed a deployment on version 1 (declares ``p`` and ``q``) of a driver whose version 2
    declares only ``q``. Return the unit of work, the deployment id and both version ids."""
    uow = FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        application_drivers=FakeApplicationDriverRepository(),
        deployments=FakeDeploymentRepository(),
    )
    driver = ApplicationDriver(name="generic")
    await uow.application_drivers.create(driver)
    version_ids = []
    for version, definitions in (("1", CURRENT), ("2", TARGET)):
        adv = ApplicationDriverVersion(
            id=uuid4(),
            version=version,
            application_supported_versions=">=1.0.0",
            helm_chart_id=uuid4(),
            source_type="local",
            source_repository="/drivers/generic",
            application_driver_id=driver.id,
            parameters=_parameter_dicts(definitions),
            services=[],
            component_configs=[],
        )
        await uow.application_driver_versions.create(adv)
        version_ids.append(adv.id)
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=version_ids[0],
        environment_id=uuid4(),
        created_by_user_id=uuid4(),
        parameters=stored,
        name="retired-rule",
    )
    await uow.deployments.save(deployment)
    return uow, deployment.id, version_ids[0], version_ids[1]


@pytest.mark.parametrize(
    ("stored", "parameters_argument", "parameter_updates", "reaches_validation"),
    [
        ({"p": 7, "q": 1}, None, {"p": 5}, {"q": 1}),
        ({"p": 7, "q": 1}, {"q": 1}, None, {"q": 1}),
        ({"p": 7, "q": 1}, {"p": 7, "q": 1}, {"p": 5}, {"q": 1}),
        ({"p": 5, "q": 1}, None, None, {"q": 1}),
    ],
    ids=[
        "input-parameters-resubmit-default",
        "parameters-argument-without-p",
        "input-parameters-on-top-of-argument",
        "stored-default",
    ],
)
async def test_version_change_drops_retired_default_from_merged_map(
    stored: dict[str, Any],
    parameters_argument: dict[str, Any] | None,
    parameter_updates: dict[str, Any] | None,
    reaches_validation: dict[str, Any],
) -> None:
    uow, deployment_id, _, target_id = await _seed(stored)

    with (
        patch(
            "styrmin_backend.services.deployment.validate_parameter_values",
            side_effect=_stop,
        ),
        pytest.raises(_StopAfterRule) as excinfo,
    ):
        await update_deployment_version(
            deployment_id=deployment_id,
            version="1.0.0",
            uow=uow,
            driver_version_id=target_id,
            deployment_parameters=parameters_argument,
            parameter_updates=parameter_updates,
        )

    assert excinfo.value.values == reaches_validation


@pytest.mark.parametrize(
    ("stored", "parameters_argument", "parameter_updates"),
    [
        ({"p": 7, "q": 1}, None, None),
        ({"p": 5, "q": 1}, None, {"p": 7}),
        ({"p": 5, "q": 1}, {"p": 7, "q": 1}, None),
    ],
    ids=["stored-changed", "input-parameters-changed", "parameters-argument-changed"],
)
async def test_version_change_rejects_changed_retired_value_in_merged_map(
    stored: dict[str, Any],
    parameters_argument: dict[str, Any] | None,
    parameter_updates: dict[str, Any] | None,
) -> None:
    uow, deployment_id, _, target_id = await _seed(stored)

    with pytest.raises(RetiredParameterValueError) as excinfo:
        await update_deployment_version(
            deployment_id=deployment_id,
            version="1.0.0",
            uow=uow,
            driver_version_id=target_id,
            deployment_parameters=parameters_argument,
            parameter_updates=parameter_updates,
        )

    assert excinfo.value.error_metadata == {
        "parameter_name": "p",
        "value": 7,
        "default": 5,
        "checked_against": CHECKED_AGAINST,
    }


async def test_rule_does_not_run_without_a_driver_version_change() -> None:
    """Bound to the same driver version, the stored map reaches validation unchanged."""
    uow, deployment_id, current_id, _ = await _seed({"p": 7, "q": 1})

    with (
        patch(
            "styrmin_backend.services.deployment.validate_parameter_values",
            side_effect=_stop,
        ),
        pytest.raises(_StopAfterRule) as excinfo,
    ):
        await update_deployment_version(
            deployment_id=deployment_id,
            version="1.0.0",
            uow=uow,
            driver_version_id=current_id,
        )

    assert excinfo.value.values == {"p": 7, "q": 1}
