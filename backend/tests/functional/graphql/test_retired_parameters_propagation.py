"""GraphQL ↔ DB propagation tests for the retired-parameter rule (023 T038, research D-007).

Two versions of one driver are loaded from local directories: version 1 declares ``p``
(default 5) and ``q`` (default 1), version 2 declares only ``q``. On ``updateDeploymentVersion``
to version 2, a ``p`` value equal to 5 is dropped and any other value is rejected with
``RETIRED_PARAMETER_VALUE`` before any task or flow run, leaving the deployment row unchanged.
The rule applies to the merged map: the ``parameters`` argument (or the stored values) plus
``input.parameters``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import yaml
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import ApplicationDriverVersion, Deployment, Task

from ._queries import load_query
from .conftest import gql
from .seeds import seed_deployment

MIGRATION_GUIDE_URL = (
    "https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters"
)
P_DEFINITION = {"name": "p", "label": "P", "kind": "integer", "default": 5}
Q_DEFINITION = {"name": "q", "label": "Q", "kind": "integer", "default": 1}


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Give the Prefect manager concrete return values so a successful reconcile dispatch
    does not leak an ``AsyncMock`` into a DB-bound column."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


def _write_driver(
    path: Path, *, name: str, version: str, parameters: list[dict[str, Any]]
) -> None:
    path.mkdir()
    spec: dict[str, Any] = {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": name},
        "spec": {
            "version": version,
            "supported_versions": ">=1.0,<2.0",
            "info": {"description": "Retired parameter fixture"},
            "helm": {
                "main": {
                    "location": "oci://registry.example.com/charts/simple-app",
                    "version": "0.1.0",
                }
            },
            "parameters": parameters,
            "components": {
                "server": {
                    "identifier": {"label": {"app.kubernetes.io/name": "server-app"}},
                    "container": "server",
                }
            },
        },
    }
    (path / "driver.styrmin.yml").write_text(yaml.safe_dump(spec))
    (path / "values.j2.yml").write_text("{}\n")


async def _load_versions(client: AsyncClient, tmp_path: Path) -> tuple[str, str, str]:
    """Load versions 1 and 2 of one driver; return the driver name and both version ids."""
    name = f"retired-params-{uuid4().hex[:8]}"
    _write_driver(
        tmp_path / "v1", name=name, version="1", parameters=[P_DEFINITION, Q_DEFINITION]
    )
    _write_driver(tmp_path / "v2", name=name, version="2", parameters=[Q_DEFINITION])
    v1 = (
        await gql(
            client, "load_local_driver_parameters", {"path": str(tmp_path / "v1")}
        )
    )["loadLocalApplicationDriverVersion"]
    v2 = (
        await gql(
            client, "load_local_driver_parameters", {"path": str(tmp_path / "v2")}
        )
    )["loadLocalApplicationDriverVersion"]
    assert v1["applicationDriverId"] == v2["applicationDriverId"]
    assert [p["name"] for p in v1["parameters"]] == ["p", "q"]
    assert [p["name"] for p in v2["parameters"]] == ["q"]
    return name, v1["id"], v2["id"]


async def _seed_on_version_1(
    session: AsyncSession, version_1_id: str, stored: dict[str, Any]
) -> UUID:
    adv = await session.get(ApplicationDriverVersion, UUID(version_1_id))
    assert adv is not None
    deployment = await seed_deployment(session, adv=adv)
    deployment.parameters = stored
    session.add(deployment)
    await session.commit()
    return deployment.id


async def _post_update_version(
    client: AsyncClient,
    deployment_id: UUID,
    driver_version_id: str,
    *,
    parameters: dict[str, Any] | None = None,
    input_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    variables: dict[str, Any] = {
        "deploymentId": str(deployment_id),
        "version": "1.0.0",
        "driverVersionId": driver_version_id,
        "parameters": parameters,
    }
    if input_parameters is not None:
        variables["input"] = {
            "parameters": [
                {"name": key, "value": value} for key, value in input_parameters.items()
            ]
        }
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_version_with_input"),
            "variables": variables,
        },
    )
    assert response.status_code == 200
    return response.json()


async def _stored_row(session: AsyncSession, deployment_id: UUID) -> Deployment:
    # Fresh SELECT: ``session.get`` would return the stale identity-map object.
    session.expire_all()
    return (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()


async def _row_snapshot(session: AsyncSession, deployment_id: UUID) -> tuple[Any, ...]:
    row = await _stored_row(session, deployment_id)
    return (
        row.config,
        row.parameters,
        row.name,
        row.status,
        row.application_version,
        row.application_driver_version_id,
    )


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(rows.all())


async def _assert_moved_to_version_2(
    session: AsyncSession, deployment_id: UUID, version_2_id: str
) -> None:
    stored = await _stored_row(session, deployment_id)
    assert stored.application_driver_version_id == UUID(version_2_id)
    assert stored.parameters == {"q": 1}
    assert await _task_count(session, deployment_id) == 1


async def _assert_rejected_without_task(
    session: AsyncSession,
    prefect_manager_mock: Any,
    deployment_id: UUID,
    snapshot_before: tuple[Any, ...],
) -> None:
    prefect_manager_mock.run_action.assert_not_awaited()
    assert await _task_count(session, deployment_id) == 0
    assert await _row_snapshot(session, deployment_id) == snapshot_before


@pytest.mark.asyncio
async def test_retired_parameter_at_its_default_is_dropped(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """A stored ``p`` equal to version 1's default moves to version 2 without a manual step,
    and the stored parameters no longer contain it."""
    _arm_prefect(prefect_manager_mock)
    _, version_1_id, version_2_id = await _load_versions(client, tmp_path)
    deployment_id = await _seed_on_version_1(session, version_1_id, {"p": 5, "q": 1})

    payload = await _post_update_version(client, deployment_id, version_2_id)

    assert "errors" not in payload, payload
    await _assert_moved_to_version_2(session, deployment_id, version_2_id)


@pytest.mark.asyncio
async def test_retired_parameter_with_a_changed_value_is_rejected(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """A stored ``p`` of 7 rejects the change with ``RETIRED_PARAMETER_VALUE``, its metadata
    and the migration guide link; no task, no flow run, the row is unchanged."""
    _arm_prefect(prefect_manager_mock)
    driver_name, version_1_id, version_2_id = await _load_versions(client, tmp_path)
    deployment_id = await _seed_on_version_1(session, version_1_id, {"p": 7, "q": 1})
    snapshot_before = await _row_snapshot(session, deployment_id)

    payload = await _post_update_version(client, deployment_id, version_2_id)

    assert "errors" in payload, payload
    error = payload["errors"][0]
    extensions = error.get("extensions") or {}
    checked_against = f"driver {driver_name} version 2 (application version 1.0.0)"
    assert extensions == {
        "code": "RETIRED_PARAMETER_VALUE",
        "parameter_name": "p",
        "value": 7,
        "default": 5,
        "checked_against": checked_against,
    }
    assert checked_against in error["message"]
    assert MIGRATION_GUIDE_URL in error["message"]
    await _assert_rejected_without_task(
        session, prefect_manager_mock, deployment_id, snapshot_before
    )


@pytest.mark.asyncio
async def test_parameters_argument_without_the_retired_key_succeeds(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """The ``parameters`` argument replaces the stored values, so leaving ``p`` out of it
    resolves the rejection in one request."""
    _arm_prefect(prefect_manager_mock)
    _, version_1_id, version_2_id = await _load_versions(client, tmp_path)
    deployment_id = await _seed_on_version_1(session, version_1_id, {"p": 7, "q": 1})

    payload = await _post_update_version(
        client, deployment_id, version_2_id, parameters={"q": 1}
    )

    assert "errors" not in payload, payload
    await _assert_moved_to_version_2(session, deployment_id, version_2_id)


@pytest.mark.asyncio
async def test_input_parameters_resubmitting_the_default_succeeds(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """``input.parameters`` merge on top of the stored values before the rule runs, so
    resubmitting ``p: 5`` drops it."""
    _arm_prefect(prefect_manager_mock)
    _, version_1_id, version_2_id = await _load_versions(client, tmp_path)
    deployment_id = await _seed_on_version_1(session, version_1_id, {"p": 7, "q": 1})

    payload = await _post_update_version(
        client, deployment_id, version_2_id, input_parameters={"p": 5}
    )

    assert "errors" not in payload, payload
    await _assert_moved_to_version_2(session, deployment_id, version_2_id)


@pytest.mark.asyncio
async def test_parameter_declared_by_neither_version_is_still_unknown(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """A typo that neither version declares is not a retired parameter: it fails with
    ``OPERATION_FAILED`` "Unknown parameter", as before the rule."""
    _arm_prefect(prefect_manager_mock)
    _, version_1_id, version_2_id = await _load_versions(client, tmp_path)
    deployment_id = await _seed_on_version_1(session, version_1_id, {"p": 5, "q": 1})
    snapshot_before = await _row_snapshot(session, deployment_id)

    payload = await _post_update_version(
        client, deployment_id, version_2_id, input_parameters={"typo": 1}
    )

    assert "errors" in payload, payload
    error = payload["errors"][0]
    assert (error.get("extensions") or {}).get("code") == "OPERATION_FAILED", error
    assert "Unknown parameter: 'typo'" in error["message"]
    await _assert_rejected_without_task(
        session, prefect_manager_mock, deployment_id, snapshot_before
    )
