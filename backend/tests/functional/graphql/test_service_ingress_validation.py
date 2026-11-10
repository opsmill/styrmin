"""Refused service ingress overrides: typed errors, nothing persisted (#598, T052; FR-009, FR-010).

Every write path that carries an override runs the validator before anything is saved or
dispatched: ``deploy``, ``updateDeployment``, ``updateDeploymentVersion`` (with and without
``input``), and the SDK ``apply`` that calls ``updateDeploymentVersion(input:)`` (ADR-065).
A refused request returns an error whose ``extensions.code`` is one of the three typed codes
and whose message names the service. The stored deployment (its config, parameters, name,
status, versions and its services), the tasks and the Prefect dispatch stay as they were.

``infrahub`` is internal, ``task-manager`` and ``api`` are external (``DECLARED_SERVICES``).
The target driver version ``2.0.0`` of each test declares the services it needs: one that makes
``task-manager`` internal, one that removes it, one that keeps it.

Written before the validator (T051) and its call sites (T052). Source:
``specs/033-service-ingress-override/spec.md`` (user story 4) and
``contracts/graphql-and-manifest.md`` (typed errors).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    DeployedService,
    Deployment,
    Task,
)

from .seeds import seed_application_driver_version
from .test_service_ingress_manifest_apply import (
    SERVICES_CONFIG,
    _apply,
    _existing,
    _write_manifest,
)
from .test_service_ingress_propagation import (
    DECLARED_SERVICES,
    OVERRIDE_CLASS,
    TASK_MANAGER_OVERRIDE_INPUT,
    TASK_MANAGER_OVERRIDE_STORED,
    _arm_prefect,
    _post,
    _post_deploy,
    _post_update,
    _post_update_version,
    _seed_deploy_driver,
    _seed_deployment,
    _stored_row,
    _task_count,
)

STORED = {"services": {"task-manager": TASK_MANAGER_OVERRIDE_STORED}}
INFRAHUB_OVERRIDE_INPUT = {"name": "infrahub", "ingressClass": OVERRIDE_CLASS}
GHOST_OVERRIDE_INPUT = {"name": "ghost", "ingressClass": OVERRIDE_CLASS}

TASK_MANAGER_INTERNAL = [
    {**declared, "scope": "internal"}
    if declared["name"] == "task-manager"
    else declared
    for declared in DECLARED_SERVICES
]
TASK_MANAGER_REMOVED = [
    declared for declared in DECLARED_SERVICES if declared["name"] != "task-manager"
]


def _checked_against(driver_name: str, driver_version: str = "1.0.0") -> str:
    return f"driver {driver_name} version {driver_version} (application version 1.0.0)"


async def _seed_driver_version_2(
    session: AsyncSession, deployment_id: UUID, services: list[dict[str, Any]]
) -> tuple[UUID, str]:
    """Version ``2.0.0`` of the deployment's driver declaring ``services``; return its id and
    the driver name."""
    deployment = await session.get(Deployment, deployment_id)
    assert deployment is not None
    current = await session.get(
        ApplicationDriverVersion, deployment.application_driver_version_id
    )
    assert current is not None
    driver = await session.get(ApplicationDriver, current.application_driver_id)
    assert driver is not None
    target = await seed_application_driver_version(
        session, driver=driver, version="2.0.0"
    )
    target.services = services
    session.add(target)
    await session.commit()
    return target.id, driver.name


async def _snapshot(session: AsyncSession, deployment_id: UUID) -> tuple[Any, ...]:
    """The stored deployment and its services, as a refused request must leave them."""
    row = await _stored_row(session, deployment_id)
    services = (
        await session.exec(
            select(DeployedService).where(
                DeployedService.deployment_id == deployment_id
            )
        )
    ).all()
    return (
        row.config,
        row.parameters,
        row.name,
        row.status,
        row.application_version,
        row.application_driver_version_id,
        sorted(
            (s.id, s.driver_service_name, s.resolved_name, s.scope) for s in services
        ),
    )


def _error(payload: dict[str, Any], code: str) -> tuple[dict[str, Any], str]:
    """Assert the only error carries ``code``; return its extensions and its message."""
    assert "errors" in payload, payload
    [error] = payload["errors"]
    extensions = error.get("extensions") or {}
    assert extensions.get("code") == code, error
    return extensions, error["message"]


async def _assert_refused_without_change(
    session: AsyncSession,
    prefect_manager_mock: Any,
    deployment_id: UUID,
    snapshot_before: tuple[Any, ...],
) -> None:
    prefect_manager_mock.run_action.assert_not_awaited()
    assert await _task_count(session, deployment_id) == 0
    assert await _snapshot(session, deployment_id) == snapshot_before


async def _assert_deploy_refused(
    session: AsyncSession, prefect_manager_mock: Any, name: str
) -> None:
    prefect_manager_mock.run_action.assert_not_awaited()
    session.expire_all()
    created = await session.exec(select(Deployment).where(Deployment.name == name))
    assert created.all() == []
    assert (await session.exec(select(Task))).all() == []


# ---------------------------------------------------------------------------
# Setting an override: the service must be declared and external (FR-009)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_refuses_an_override_on_an_internal_service(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(
        session, config={"ip_whitelist": ["10.0.0.0/8"]}
    )
    before = await _snapshot(session, deployment_id)

    payload = await _post_update(
        client, deployment_id, {"services": [INFRAHUB_OVERRIDE_INPUT]}
    )

    extensions, message = _error(payload, "SERVICE_INGRESS_NOT_BUILT")
    assert extensions["service_name"] == "infrahub"
    assert extensions["scope"] == "internal"
    assert "'infrahub'" in message
    assert "does not build its Ingress" in message
    await _assert_refused_without_change(
        session, prefect_manager_mock, deployment_id, before
    )


@pytest.mark.asyncio
async def test_update_deployment_refuses_an_override_on_an_unknown_service(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)
    before = await _snapshot(session, deployment_id)

    payload = await _post_update(
        client, deployment_id, {"services": [GHOST_OVERRIDE_INPUT]}
    )

    extensions, message = _error(payload, "UNKNOWN_SERVICE_INGRESS_OVERRIDE")
    assert extensions["service_name"] == "ghost"
    assert extensions["known_services"] == ["api", "infrahub", "task-manager"]
    assert "'ghost'" in message
    await _assert_refused_without_change(
        session, prefect_manager_mock, deployment_id, before
    )


@pytest.mark.asyncio
async def test_update_deployment_refuses_the_whole_request_when_one_override_is_invalid(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A valid override next to an invalid one is not stored either."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)
    before = await _snapshot(session, deployment_id)

    payload = await _post_update(
        client,
        deployment_id,
        {"services": [TASK_MANAGER_OVERRIDE_INPUT, INFRAHUB_OVERRIDE_INPUT]},
    )

    _error(payload, "SERVICE_INGRESS_NOT_BUILT")
    await _assert_refused_without_change(
        session, prefect_manager_mock, deployment_id, before
    )


@pytest.mark.asyncio
async def test_update_deployment_stores_an_override_on_an_external_service(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """The control of the refusals above: the same call on an external service is stored."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)

    payload = await _post_update(
        client, deployment_id, {"services": [TASK_MANAGER_OVERRIDE_INPUT]}
    )

    assert "errors" not in payload, payload
    assert (await _stored_row(session, deployment_id)).config == STORED


@pytest.mark.asyncio
async def test_update_deployment_clears_an_override_on_a_service_that_is_now_internal(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """The stored override targets ``infrahub``, which the driver version declares internal.
    A request that leaves it out clears it (SC-004)."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(
        session, config={"services": {"infrahub": {"ingress_class": OVERRIDE_CLASS}}}
    )

    payload = await _post_update(client, deployment_id, {"services": []})

    assert "errors" not in payload, payload
    assert not ((await _stored_row(session, deployment_id)).config or {}).get(
        "services"
    )


@pytest.mark.asyncio
async def test_deploy_refuses_an_override_on_an_internal_service(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(session)

    name, payload = await _post_deploy(
        client, driver_name, environment_id, {"services": [INFRAHUB_OVERRIDE_INPUT]}
    )

    extensions, message = _error(payload, "SERVICE_INGRESS_NOT_BUILT")
    assert extensions["service_name"] == "infrahub"
    assert extensions["checked_against"] == _checked_against(driver_name)
    assert "'infrahub'" in message
    await _assert_deploy_refused(session, prefect_manager_mock, name)


@pytest.mark.asyncio
async def test_deploy_refuses_an_override_on_an_unknown_service(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(session)

    name, payload = await _post_deploy(
        client, driver_name, environment_id, {"services": [GHOST_OVERRIDE_INPUT]}
    )

    extensions, _message = _error(payload, "UNKNOWN_SERVICE_INGRESS_OVERRIDE")
    assert extensions["service_name"] == "ghost"
    await _assert_deploy_refused(session, prefect_manager_mock, name)


# ---------------------------------------------------------------------------
# A driver version change must not drop a stored override (FR-010)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_services", "reason"),
    [(TASK_MANAGER_INTERNAL, "internal"), (TASK_MANAGER_REMOVED, "removed")],
    ids=["internalized", "removed"],
)
@pytest.mark.parametrize(
    "sends_input", [False, True], ids=["no-input", "input-sent-again"]
)
async def test_update_deployment_version_refuses_to_drop_a_stored_override(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    target_services: list[dict[str, Any]],
    reason: str,
    sends_input: bool,
) -> None:
    """Without ``input`` the stored config is checked; with the ``input`` that ``apply`` sends,
    the config the request carries is. Both refuse, before any task or dispatch."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session, config=STORED)
    target_id, _ = await _seed_driver_version_2(session, deployment_id, target_services)
    before = await _snapshot(session, deployment_id)

    if sends_input:
        payload = await _post_update_version(
            client,
            deployment_id,
            target_id,
            {"services": [TASK_MANAGER_OVERRIDE_INPUT]},
        )
    else:
        payload = await _post(
            client,
            "update_deployment_version",
            {
                "deploymentId": str(deployment_id),
                "version": "1.0.0",
                "driverVersionId": str(target_id),
            },
        )

    extensions, message = _error(payload, "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED")
    assert extensions["service_name"] == "task-manager"
    assert extensions["current_version"] == "1.0.0"
    assert extensions["target_version"] == "2.0.0"
    assert extensions["reason"] == reason
    assert "'task-manager'" in message
    await _assert_refused_without_change(
        session, prefect_manager_mock, deployment_id, before
    )
    assert (await _stored_row(session, deployment_id)).config == STORED


@pytest.mark.asyncio
async def test_update_deployment_version_reports_a_new_override_on_a_removed_service_as_unknown(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Nothing is stored for ``task-manager`` yet, so nothing would be dropped: the override
    that the request sets is the one the target version cannot honour."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session)
    target_id, driver_name = await _seed_driver_version_2(
        session, deployment_id, TASK_MANAGER_REMOVED
    )
    before = await _snapshot(session, deployment_id)

    payload = await _post_update_version(
        client, deployment_id, target_id, {"services": [TASK_MANAGER_OVERRIDE_INPUT]}
    )

    extensions, _message = _error(payload, "UNKNOWN_SERVICE_INGRESS_OVERRIDE")
    assert extensions["service_name"] == "task-manager"
    assert extensions["checked_against"] == _checked_against(driver_name, "2.0.0")
    await _assert_refused_without_change(
        session, prefect_manager_mock, deployment_id, before
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config_input",
    [{"services": []}, {"ipWhitelist": ["10.0.0.0/8"]}],
    ids=["empty-list", "other-field-only"],
)
async def test_update_deployment_version_allows_clearing_the_override_in_the_same_request(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    config_input: dict[str, Any],
) -> None:
    """SC-004: the request that moves to a version without the service also clears its override,
    so the version changes and the override is gone, not dropped silently."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session, config=STORED)
    target_id, _ = await _seed_driver_version_2(
        session, deployment_id, TASK_MANAGER_REMOVED
    )

    payload = await _post_update_version(client, deployment_id, target_id, config_input)

    assert "errors" not in payload, payload
    row = await _stored_row(session, deployment_id)
    assert row.application_driver_version_id == target_id
    assert not (row.config or {}).get("services")
    assert await _task_count(session, deployment_id) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sends_input", [False, True], ids=["no-input", "input-sent-again"]
)
async def test_update_deployment_version_keeps_an_override_on_a_service_that_stays_external(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    sends_input: bool,
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_deployment(session, config=STORED)
    target_id, _ = await _seed_driver_version_2(
        session, deployment_id, DECLARED_SERVICES
    )

    if sends_input:
        payload = await _post_update_version(
            client,
            deployment_id,
            target_id,
            {"services": [TASK_MANAGER_OVERRIDE_INPUT]},
        )
    else:
        payload = await _post(
            client,
            "update_deployment_version",
            {
                "deploymentId": str(deployment_id),
                "version": "1.0.0",
                "driverVersionId": str(target_id),
            },
        )

    assert "errors" not in payload, payload
    row = await _stored_row(session, deployment_id)
    assert row.application_driver_version_id == target_id
    assert row.config == STORED
    assert await _task_count(session, deployment_id) == 1


# ---------------------------------------------------------------------------
# ``apply`` reaches the same validation, through updateDeploymentVersion (ADR-065)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_refuses_a_version_change_that_would_drop_the_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """The manifest keeps the override and the newest loaded driver version makes
    ``task-manager`` internal: ``apply`` fails with the typed code and writes nothing."""
    _arm_prefect(prefect_manager_mock)
    name, driver_name = await _existing(session, config=STORED)
    deployment = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    deployment_id = deployment.id
    await _seed_driver_version_2(session, deployment_id, TASK_MANAGER_INTERNAL)
    before = await _snapshot(session, deployment_id)
    manifest = _write_manifest(
        tmp_path / "app.yaml", name=name, driver=driver_name, config=SERVICES_CONFIG
    )

    outcome = await _apply(client, manifest)

    assert outcome.action == "failed", outcome
    assert outcome.error_code == "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED", outcome
    assert outcome.failure_reason is not None
    assert "'task-manager'" in outcome.failure_reason
    await _assert_refused_without_change(
        session, prefect_manager_mock, deployment_id, before
    )


@pytest.mark.asyncio
async def test_apply_refuses_an_override_on_an_internal_service(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    _arm_prefect(prefect_manager_mock)
    name, driver_name = await _existing(session, config={})
    deployment = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    deployment_id = deployment.id
    before = await _snapshot(session, deployment_id)
    manifest = _write_manifest(
        tmp_path / "app.yaml",
        name=name,
        driver=driver_name,
        config=f"    services:\n      - name: infrahub\n        ingress_class: {OVERRIDE_CLASS}\n",
    )

    outcome = await _apply(client, manifest)

    assert outcome.action == "failed", outcome
    assert outcome.error_code == "SERVICE_INGRESS_NOT_BUILT", outcome
    await _assert_refused_without_change(
        session, prefect_manager_mock, deployment_id, before
    )


@pytest.mark.asyncio
async def test_apply_allows_the_version_change_when_the_manifest_clears_the_override(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """A manifest with a config and no ``services`` clears the override (full replacement), so
    the move to a driver version without the service goes through."""
    _arm_prefect(prefect_manager_mock)
    name, driver_name = await _existing(session, config=STORED)
    deployment = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    deployment_id = deployment.id
    target_id, _ = await _seed_driver_version_2(
        session, deployment_id, TASK_MANAGER_REMOVED
    )
    manifest = _write_manifest(
        tmp_path / "app.yaml",
        name=name,
        driver=driver_name,
        config="    ip_whitelist:\n      - 10.0.0.0/8\n",
    )

    outcome = await _apply(client, manifest)

    assert outcome.action == "updated", outcome
    row = await _stored_row(session, deployment_id)
    assert row.application_driver_version_id == target_id
    assert row.config == {"ip_whitelist": ["10.0.0.0/8"]}
