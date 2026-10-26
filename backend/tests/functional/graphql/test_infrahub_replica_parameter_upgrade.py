"""The infrahub drivers move from replica parameters to driver defaults (023 US4, T039, T040).

A deployment is created on the driver version kept in ``fixtures/legacy_drivers/`` (``infrahub``
4, ``infrahub-enterprise`` 3), which declares the ``replicas_server`` and
``replicas_task_worker`` parameters. The current example driver (``infrahub`` 5,
``infrahub-enterprise`` 4) is then loaded and the deployment changes to it through
``updateDeploymentVersion``:

- SC-004: with the default parameter values the change needs no manual step, the two values are
  dropped, and each component resolves to the count the old version rendered.
- SC-005: a changed value is rejected with ``RETIRED_PARAMETER_VALUE`` and the deployment stays on
  the old version until the value is carried over as a replica override, in one request or in
  two steps (edit, then upgrade).
- Critique E4: the nested ``updateDeploymentVersion`` that the ``upgrade`` hook's
  ``upgrade_deployment_version`` primitive sends after the outer change is a no-op.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from .conftest import gql
from .seeds import seed_environment
from .test_replica_overrides_propagation import (
    _arm_prefect,
    _assert_error,
    _post,
    _read_rows,
    _row,
    _row_snapshot,
    _stored_row,
    _task_count,
)

_LEGACY_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "legacy_drivers"
_EXAMPLES_DIR = Path(__file__).resolve().parents[4] / "driver" / "examples"
APP_VERSION = "1.5.0"
MIGRATION_GUIDE_URL = (
    "https://docs.styrmin.app/docs/drivers/migrating-replica-parameters"
)
DEFAULT_PARAMETERS = {
    "replicas_server": 1,
    "replicas_task_worker": 2,
    "database_storage_size": 100,
    "enable_analytics": True,
}
KEPT_PARAMETERS = {"database_storage_size": 100, "enable_analytics": True}


@dataclass(frozen=True)
class _Upgrade:
    driver: str
    legacy_dir: str
    old_version: str
    new_version: str


INFRAHUB = _Upgrade("infrahub", "infrahub-v4", "4", "5")
INFRAHUB_ENTERPRISE = _Upgrade(
    "infrahub-enterprise", "infrahub-enterprise-v3", "3", "4"
)


def _new_version_rows(
    task_worker: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """``componentReplicas`` on the new version, with no override unless ``task_worker``."""
    rows = {
        "cache": _row("cache", 1, "DRIVER_DEFAULT", singleton=True),
        "database": _row("database", 1, "DRIVER_DEFAULT", singleton=True),
        "message-queue": _row("message-queue", None, "CHART"),
        "server": _row("server", 1, "DRIVER_DEFAULT"),
        "task-manager": _row("task-manager", None, "CHART"),
        "task-manager-db": _row("task-manager-db", 1, "DRIVER_DEFAULT", singleton=True),
        "task-worker": task_worker or _row("task-worker", 2, "DRIVER_DEFAULT"),
    }
    return [rows[name] for name in sorted(rows)]


async def _load(client: AsyncClient, source: Path, tmp_path: Path) -> dict[str, Any]:
    copy = tmp_path / source.name
    shutil.copytree(source, copy)
    data = await gql(client, "load_local_driver_parameters", {"path": str(copy)})
    return data["loadLocalApplicationDriverVersion"]


async def _deploy_on_old_version(
    client: AsyncClient,
    session: AsyncSession,
    tmp_path: Path,
    upgrade: _Upgrade = INFRAHUB,
    parameters: dict[str, Any] | None = None,
) -> tuple[UUID, str]:
    """Deploy on the legacy driver version, then load the new one, as a user would.

    Return the deployment id and the new driver version id.
    """
    old = await _load(client, _LEGACY_DIR / upgrade.legacy_dir, tmp_path)
    assert old["version"] == upgrade.old_version
    environment = await seed_environment(session)
    payload = await _post(
        client,
        "deploy",
        {
            "driver": upgrade.driver,
            "version": APP_VERSION,
            "environmentId": str(environment.id),
            "name": f"{upgrade.driver}-upgrade",
            "parameters": [
                {"name": key, "value": value}
                for key, value in (parameters or {}).items()
            ],
        },
    )
    assert "errors" not in payload, payload
    deployment_id = UUID(payload["data"]["deploy"]["deploymentId"])
    stored = await _stored_row(session, deployment_id)
    assert stored.application_driver_version_id == UUID(old["id"])

    new = await _load(client, _EXAMPLES_DIR / upgrade.driver, tmp_path)
    assert new["version"] == upgrade.new_version
    assert new["applicationDriverId"] == old["applicationDriverId"]
    return deployment_id, new["id"]


async def _change_version(
    client: AsyncClient,
    deployment_id: UUID,
    driver_version_id: str,
    *,
    parameters: dict[str, Any] | None = None,
    components: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``updateDeploymentVersion`` pinned to ``driver_version_id``; with neither keyword it is
    what the UI upgrade dialog sends."""
    variables: dict[str, Any] = {
        "deploymentId": str(deployment_id),
        "version": APP_VERSION,
        "driverVersionId": driver_version_id,
        "parameters": parameters,
    }
    if components is not None:
        variables["input"] = {"components": components}
    return await _post(client, "update_deployment_version_with_input", variables)


def _checked_against(upgrade: _Upgrade) -> str:
    return (
        f"driver {upgrade.driver} version {upgrade.new_version} "
        f"(application version {APP_VERSION})"
    )


async def _assert_moved(
    session: AsyncSession,
    deployment_id: UUID,
    new_version_id: str,
    *,
    components: dict[str, Any] | None = None,
) -> None:
    stored = await _stored_row(session, deployment_id)
    assert stored.application_driver_version_id == UUID(new_version_id)
    assert stored.parameters == KEPT_PARAMETERS
    assert ((stored.config or {}).get("components") or {}) == (components or {})


# ---------------------------------------------------------------------------
# T039 — default values move; a changed value is rejected until carried over
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upgrade", [INFRAHUB, INFRAHUB_ENTERPRISE], ids=lambda u: u.driver
)
async def test_default_parameter_values_move_without_a_manual_step(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    tmp_path: Path,
    upgrade: _Upgrade,
) -> None:
    """SC-004: the create path stored every default, the change drops the two replica
    parameters, and ``server`` and ``task-worker`` resolve to the counts they held."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_version_id = await _deploy_on_old_version(
        client, session, tmp_path, upgrade
    )
    # A copy: the row object is refreshed in place by the next read.
    before = dict((await _stored_row(session, deployment_id)).parameters)
    assert before == DEFAULT_PARAMETERS
    # On the old version the parameters set the counts; Styrmin patches none.
    assert {row["source"] for row in await _read_rows(client, deployment_id)} == {
        "CHART"
    }

    payload = await _change_version(client, deployment_id, new_version_id)

    assert "errors" not in payload, payload
    await _assert_moved(session, deployment_id, new_version_id)
    assert await _task_count(session, deployment_id) == 2
    rows = await _read_rows(client, deployment_id)
    assert rows == _new_version_rows()
    counts = {row["component"]: row["count"] for row in rows}
    assert counts["server"] == before["replicas_server"]
    assert counts["task-worker"] == before["replicas_task_worker"]


@pytest.mark.asyncio
async def test_changed_task_worker_count_is_rejected(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """SC-005: ``replicas_task_worker: 4`` rejects the change with the parameter, its value
    and the migration guide; no task or flow run starts and the deployment stays on 4."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_version_id = await _deploy_on_old_version(
        client, session, tmp_path, parameters={"replicas_task_worker": 4}
    )
    snapshot = await _row_snapshot(session, deployment_id)
    flow_runs = prefect_manager_mock.run_action.await_count

    payload = await _change_version(client, deployment_id, new_version_id)

    message = _assert_error(
        payload,
        "RETIRED_PARAMETER_VALUE",
        parameter_name="replicas_task_worker",
        value=4,
        default=2,
        checked_against=_checked_against(INFRAHUB),
    )
    assert "'replicas_task_worker'" in message
    assert "sets it to 4" in message
    assert MIGRATION_GUIDE_URL in message
    assert prefect_manager_mock.run_action.await_count == flow_runs
    assert await _task_count(session, deployment_id) == 1
    assert await _row_snapshot(session, deployment_id) == snapshot


@pytest.mark.asyncio
async def test_resubmitting_with_a_replica_override_succeeds(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """One request resolves the rejection: a ``task-worker`` override of 4 and ``parameters``
    without ``replicas_task_worker``. The ``replicas_server: 1`` left in them is dropped."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_version_id = await _deploy_on_old_version(
        client, session, tmp_path, parameters={"replicas_task_worker": 4}
    )
    rejected = await _change_version(client, deployment_id, new_version_id)
    _assert_error(rejected, "RETIRED_PARAMETER_VALUE")
    stored = await _stored_row(session, deployment_id)
    parameters = {
        key: value
        for key, value in stored.parameters.items()
        if key != "replicas_task_worker"
    }
    assert parameters["replicas_server"] == 1

    payload = await _change_version(
        client,
        deployment_id,
        new_version_id,
        parameters=parameters,
        components=[{"name": "task-worker", "replicas": 4}],
    )

    assert "errors" not in payload, payload
    await _assert_moved(
        session,
        deployment_id,
        new_version_id,
        components={"task-worker": {"replicas": 4}},
    )
    assert await _read_rows(client, deployment_id) == _new_version_rows(
        task_worker=_row("task-worker", 4, "OVERRIDE", override=4)
    )


@pytest.mark.asyncio
async def test_override_set_on_the_old_version_stays_applied(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """A ``task-worker`` override set on version 4 is checked against version 5 on the change
    and still applies there."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_version_id = await _deploy_on_old_version(
        client, session, tmp_path
    )
    updated = await _post(
        client,
        "update_deployment_config",
        {
            "deploymentId": str(deployment_id),
            "input": {"components": [{"name": "task-worker", "replicas": 3}]},
        },
    )
    assert "errors" not in updated, updated
    old_rows = {
        row["component"]: row for row in await _read_rows(client, deployment_id)
    }
    assert old_rows["task-worker"] == _row("task-worker", 3, "OVERRIDE", override=3)

    payload = await _change_version(client, deployment_id, new_version_id)

    assert "errors" not in payload, payload
    await _assert_moved(
        session,
        deployment_id,
        new_version_id,
        components={"task-worker": {"replicas": 3}},
    )
    assert await _read_rows(client, deployment_id) == _new_version_rows(
        task_worker=_row("task-worker", 3, "OVERRIDE", override=3)
    )


# ---------------------------------------------------------------------------
# T040 — the upgrade hook's nested call, and the two-step UI path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upgrade_hook_nested_version_change_changes_nothing(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """Critique E4: after the outer change to version 5, the primitive's
    ``updateDeploymentVersion`` (same application version, no driver version, no parameters)
    resolves to the bound version 5, so the retired-parameter rule does not run again and the
    call is a no-op."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_version_id = await _deploy_on_old_version(
        client, session, tmp_path
    )
    outer = await _change_version(client, deployment_id, new_version_id)
    assert "errors" not in outer, outer
    snapshot = await _row_snapshot(session, deployment_id)
    tasks = await _task_count(session, deployment_id)
    flow_runs = prefect_manager_mock.run_action.await_count

    nested = await _post(
        client,
        "update_deployment_version",
        {"deploymentId": str(deployment_id), "version": APP_VERSION},
    )

    assert "errors" not in nested, nested
    assert nested["data"]["updateDeploymentVersion"] is None
    assert await _row_snapshot(session, deployment_id) == snapshot
    assert await _task_count(session, deployment_id) == tasks
    assert prefect_manager_mock.run_action.await_count == flow_runs
    await _assert_moved(session, deployment_id, new_version_id)
    assert await _read_rows(client, deployment_id) == _new_version_rows()


@pytest.mark.asyncio
async def test_two_step_ui_path_keeps_the_task_worker_count(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, tmp_path: Path
) -> None:
    """Step 1, the edit drawer on version 4: set the ``task-worker`` override to 4 and reset
    ``replicas_task_worker`` to 2; the override already sets the count. Step 2, the upgrade
    dialog: the change to version 5 succeeds and the count stays 4."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_version_id = await _deploy_on_old_version(
        client, session, tmp_path, parameters={"replicas_task_worker": 4}
    )

    edited = await _post(
        client,
        "update_deployment_config",
        {
            "deploymentId": str(deployment_id),
            "input": {
                "components": [{"name": "task-worker", "replicas": 4}],
                "parameters": [{"name": "replicas_task_worker", "value": 2}],
            },
        },
    )
    assert "errors" not in edited, edited
    stored = await _stored_row(session, deployment_id)
    assert stored.parameters == DEFAULT_PARAMETERS
    old_rows = {
        row["component"]: row for row in await _read_rows(client, deployment_id)
    }
    assert old_rows["task-worker"] == _row("task-worker", 4, "OVERRIDE", override=4)

    payload = await _post(
        client,
        "update_deployment_version",
        {
            "deploymentId": str(deployment_id),
            "version": APP_VERSION,
            "driverVersionId": new_version_id,
        },
    )

    assert "errors" not in payload, payload
    await _assert_moved(
        session,
        deployment_id,
        new_version_id,
        components={"task-worker": {"replicas": 4}},
    )
    assert await _read_rows(client, deployment_id) == _new_version_rows(
        task_worker=_row("task-worker", 4, "OVERRIDE", override=4)
    )
