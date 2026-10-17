"""Affinity terms that name a deployment: rename (027 US1, #492), delete and re-create (US4).

Environment E has deployments A and B. B's config has a pod affinity term and E's
config has a pod anti-affinity term, both written with ``deploymentName: a``. Before
027 the rename of A was refused, because it built A's new instance with E's term and
looked the old name up. The terms now store A's id, so the rename and every later
update and config fan-out redeploy succeed.

Once A is a tombstoned deployment, the terms still give its id. Every update or
redeploy that expands such a term is refused with the term's path, A's last name and
``deleted``. Writing the term again with A's name binds it to a new deployment named A.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Component,
    Deployment,
    DeploymentState,
    Environment,
    Task,
)
from styrmin_backend.repository.deployment import SQLModelDeploymentRepository
from styrmin_backend.services import cluster_config_fanout
from styrmin_backend.services.exceptions import UnresolvableAffinityReferenceError

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

_TOPOLOGY_KEY = "kubernetes.io/hostname"
_B_TERM_PATH = "deployment.config.scheduling.pod_affinity.preferred[0].term"
_E_TERM_PATH = "environment.config.scheduling.pod_anti_affinity.preferred[0].term"


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    return prefect_manager_mock


@pytest.fixture
def patch_crd(mocker) -> AsyncMock:
    """Stand in for the cluster-side patch that ``deleteDeployment`` sends."""
    return mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource",
        new_callable=AsyncMock,
    )


@dataclass(frozen=True)
class _Environment:
    environment_id: UUID
    a_id: UUID
    b_id: UUID


def _term_input(deployment_ref: dict[str, str]) -> dict[str, Any]:
    return {
        "preferred": [
            {
                "weight": 100,
                "term": {"topologyKey": _TOPOLOGY_KEY, "deploymentRef": deployment_ref},
            }
        ]
    }


def _stored_term(deployment_id: UUID) -> dict[str, Any]:
    return {
        "preferred": [
            {
                "weight": 100,
                "term": {
                    "topology_key": _TOPOLOGY_KEY,
                    "deployment_ref": {"deployment_id": str(deployment_id)},
                },
            }
        ]
    }


def _selector(deployment_id: UUID) -> dict[str, Any]:
    return {"match_labels": {"styrmin/deployment_id": str(deployment_id)}}


def _logged(log: MagicMock) -> list[str]:
    return [
        call.args[0].format(*call.args[1:]) for call in log.call_args_list if call.args
    ]


def _fields(line: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in line.split()[1:])


async def _set_up(
    client: AsyncClient,
    session: AsyncSession,
    *,
    b_names_a: bool = True,
    e_names_a: bool = True,
) -> _Environment:
    """Write B's and E's terms with A's name, through the mutations an operator uses."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    a = await seed_deployment(session, environment=environment, adv=adv, name="a")
    b = await seed_deployment(session, environment=environment, adv=adv, name="b")
    session.add(
        Component(
            name="server",
            config={"identifier": {"label": {"app": "server"}}},
            enabled=True,
            deployment_id=b.id,
        )
    )
    await session.commit()
    ids = _Environment(environment.id, a.id, b.id)

    if b_names_a:
        await gql(
            client,
            "update_deployment",
            {
                "deploymentId": str(ids.b_id),
                "input": {
                    "scheduling": {"podAffinity": _term_input({"deploymentName": "a"})}
                },
            },
        )
    if e_names_a:
        await gql(
            client,
            "update_environment",
            {
                "environmentId": str(ids.environment_id),
                "input": {
                    "scheduling": {
                        "podAntiAffinity": _term_input({"deploymentName": "a"})
                    }
                },
            },
        )
    return ids


async def _rename_a(client: AsyncClient, ids: _Environment) -> None:
    await gql(
        client,
        "update_deployment",
        {"deploymentId": str(ids.a_id), "input": {"name": "a2"}},
    )


async def _configs(client: AsyncClient, ids: _Environment) -> tuple[dict, dict]:
    b = await gql(client, "get_deployment_config", {"deploymentId": str(ids.b_id)})
    e = await gql(
        client, "get_environment_config", {"environmentId": str(ids.environment_id)}
    )
    return b["deployment"]["config"], e["environment"]["config"]


async def _resolved_scheduling(client: AsyncClient, deployment_id: UUID) -> list[dict]:
    data = await gql(
        client,
        "get_deployment_resolved_scheduling",
        {"deploymentId": str(deployment_id)},
    )
    return data["deployment"]["resolvedScheduling"]


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(list(rows.all()))


async def _post(
    client: AsyncClient, operation: str, variables: dict[str, Any]
) -> dict[str, Any]:
    """POST an operation and return the whole payload, errors included."""
    response = await client.post(
        "/graphql", json={"query": load_query(operation), "variables": variables}
    )
    assert response.status_code == 200
    return response.json()


async def _tombstone(
    client: AsyncClient, session: AsyncSession, deployment_id: UUID
) -> None:
    """Delete the deployment, then report ``Deleted`` as the operator does once the
    workload is gone. The status report is the only path that tombstones a row."""
    await gql(client, "delete_deployment", {"deploymentId": str(deployment_id)})
    await gql(
        client,
        "report_deployment_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(deployment_id),
                    "phase": "Deleted",
                    "displayState": "Deleted",
                }
            ]
        },
    )
    session.expire_all()
    row = await session.get(Deployment, deployment_id)
    assert row is not None
    assert row.status == DeploymentState.DELETED
    assert row.deleted_at is not None


def _names_tombstoned_a(a_id: UUID, path: str) -> dict[str, Any]:
    """The metadata of the refusal of a term that gives tombstoned A's id."""
    return {
        "deployment_id": str(a_id),
        "deployment_name": "a",
        "path": path,
        "deleted": True,
    }


def _capture_logged_errors(mocker) -> list[tuple[str, BaseException | None]]:
    """Patch ``logger.exception`` and record each line with the error being handled."""
    logged: list[tuple[str, BaseException | None]] = []

    def _record(message: str, *args: object) -> None:
        logged.append((message.format(*args), sys.exc_info()[1]))

    mocker.patch.object(cluster_config_fanout.logger, "exception", side_effect=_record)
    return logged


def _dispatch_error(
    logged: list[tuple[str, BaseException | None]], fan_out: str
) -> tuple[dict[str, str], BaseException | None]:
    [(line, error)] = [
        (line, error)
        for line, error in logged
        if line.startswith(f"{fan_out}_dispatch_error ")
    ]
    return _fields(line), error


@pytest.mark.asyncio
async def test_rename_of_a_named_deployment_succeeds_and_changes_no_stored_term(
    client: AsyncClient, session: AsyncSession
) -> None:
    """US1 scenario 1 and FR-010: the rename succeeds, and B's and E's stored terms
    still give A's id."""
    ids = await _set_up(client, session)
    b_config, e_config = await _configs(client, ids)
    assert b_config == {"scheduling": {"pod_affinity": _stored_term(ids.a_id)}}
    assert e_config == {"scheduling": {"pod_anti_affinity": _stored_term(ids.a_id)}}

    # ``gql`` asserts that the response has no error.
    await _rename_a(client, ids)

    session.expire_all()
    a = await session.get(Deployment, ids.a_id)
    assert a is not None
    assert a.name == "a2"
    assert await _configs(client, ids) == (b_config, e_config)


@pytest.mark.asyncio
async def test_update_of_b_after_the_rename_succeeds(
    client: AsyncClient, session: AsyncSession
) -> None:
    """US1 scenario 2: B's update, with its term written back as read, starts a
    reconcile and keeps A's id."""
    ids = await _set_up(client, session)
    await _rename_a(client, ids)

    data = await gql(
        client,
        "update_deployment",
        {
            "deploymentId": str(ids.b_id),
            "input": {
                "envVars": [{"name": "FOO", "value": "bar"}],
                "scheduling": {
                    "podAffinity": _term_input({"deploymentId": str(ids.a_id)})
                },
            },
        },
    )

    assert data["updateDeployment"] is not None
    b_config, _ = await _configs(client, ids)
    assert b_config == {
        "env_vars": {"FOO": "bar"},
        "scheduling": {"pod_affinity": _stored_term(ids.a_id)},
    }


@pytest.mark.asyncio
async def test_environment_fan_out_after_the_rename_fails_no_redeploy(
    client: AsyncClient, session: AsyncSession, mocker
) -> None:
    """US1 scenario 3: ``updateEnvironment`` with a changed env var redeploys A and B,
    and no redeploy fails."""
    ids = await _set_up(client, session)
    await _rename_a(client, ids)
    before = {d: await _task_count(session, d) for d in (ids.a_id, ids.b_id)}
    # Both modules share the loguru logger; the lines are told apart by their key.
    log_info = mocker.patch.object(cluster_config_fanout.logger, "info")

    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(ids.environment_id),
            "input": {
                "envVars": [{"name": "FOO", "value": "bar"}],
                "scheduling": {
                    "podAntiAffinity": _term_input({"deploymentId": str(ids.a_id)})
                },
            },
        },
    )

    [line] = [
        line
        for line in _logged(log_info)
        if line.startswith("env_config_fanout_dispatched ")
    ]
    fields = _fields(line)
    assert fields["dispatched"] == "2"
    assert fields["dispatch_failed"] == "0"
    assert fields["evaluation_failed"] == "0"
    session.expire_all()
    after = {d: await _task_count(session, d) for d in (ids.a_id, ids.b_id)}
    assert after == {d: count + 1 for d, count in before.items()}


@pytest.mark.asyncio
async def test_resolved_scheduling_of_b_selects_a_s_id_after_the_rename(
    client: AsyncClient, session: AsyncSession
) -> None:
    """US1 scenario 4 and FR-010: B's ``resolvedScheduling`` is the same before and
    after the rename, and both terms select ``styrmin/deployment_id=<A's id>``."""
    ids = await _set_up(client, session)
    before = await _resolved_scheduling(client, ids.b_id)

    await _rename_a(client, ids)

    after = await _resolved_scheduling(client, ids.b_id)
    assert after == before
    [entry] = after
    assert entry["componentName"] == "server"
    config = entry["config"]
    for block in ("pod_affinity", "pod_anti_affinity"):
        [weighted] = config[block]["preferred"]
        assert weighted["term"]["label_selector"] == _selector(ids.a_id)
        assert "deployment_ref" not in weighted["term"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_crd")
@pytest.mark.parametrize("change", ["config_written_back", "rename_only"])
async def test_update_of_b_is_refused_once_the_named_deployment_is_tombstoned(
    client: AsyncClient, session: AsyncSession, change: str
) -> None:
    """US4 scenario 1: B's term still gives tombstoned A's id, so ``updateDeployment``
    on B is refused with the term's path, A's last name and ``deleted``, and saves
    nothing. A rename alone is refused too, because every update binds B's config."""
    ids = await _set_up(client, session, e_names_a=False)
    await _tombstone(client, session, ids.a_id)
    tasks_before = await _task_count(session, ids.b_id)
    update: dict[str, Any] = (
        {"name": "b2"}
        if change == "rename_only"
        else {
            "envVars": [{"name": "FOO", "value": "bar"}],
            "scheduling": {"podAffinity": _term_input({"deploymentId": str(ids.a_id)})},
        }
    )

    payload = await _post(
        client, "update_deployment", {"deploymentId": str(ids.b_id), "input": update}
    )

    [error] = payload["errors"]
    assert error["extensions"] == {
        "code": "VALIDATION_ERROR",
        **_names_tombstoned_a(ids.a_id, _B_TERM_PATH),
    }
    session.expire_all()
    b = await session.get(Deployment, ids.b_id)
    assert b is not None
    assert b.name == "b"
    assert b.config == {"scheduling": {"pod_affinity": _stored_term(ids.a_id)}}
    assert await _task_count(session, ids.b_id) == tasks_before


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_crd")
@pytest.mark.parametrize("b_redeploys", ["first", "last"])
async def test_environment_fan_out_fails_b_s_redeploy_and_keeps_c_s(
    client: AsyncClient, session: AsyncSession, mocker, b_redeploys: str
) -> None:
    """US4 scenario 2 with B's own term: in the fan-out of ``updateEnvironment``, B's
    redeploy fails with A's last name and is counted as failed. C, whose config names
    no deployment, is redeployed and its redeploy is committed, before or after B's."""
    ids = await _set_up(client, session, e_names_a=False)
    environment = await session.get(Environment, ids.environment_id)
    assert environment is not None
    c_id = (await seed_deployment(session, environment=environment, name="c")).id
    await _tombstone(client, session, ids.a_id)
    b = await session.get(Deployment, ids.b_id)
    assert b is not None
    b_instance_id = b.active_application_instance_id
    tasks_before = {d: await _task_count(session, d) for d in (ids.b_id, c_id)}
    # The listing has no order; sort it so each run puts B's redeploy at a known place.
    original = SQLModelDeploymentRepository.find_all_by_environment

    async def _in_name_order(
        self: SQLModelDeploymentRepository, environment_id: UUID, **kwargs: Any
    ) -> list:
        rows = await original(self, environment_id, **kwargs)
        return sorted(rows, key=lambda row: row.name, reverse=b_redeploys == "last")

    mocker.patch.object(
        SQLModelDeploymentRepository, "find_all_by_environment", _in_name_order
    )
    log_info = mocker.patch.object(cluster_config_fanout.logger, "info")
    logged = _capture_logged_errors(mocker)

    data = await gql(
        client,
        "update_environment",
        {
            "environmentId": str(ids.environment_id),
            "input": {"envVars": [{"name": "FOO", "value": "bar"}]},
        },
    )

    assert data["updateEnvironment"]["config"] == {"env_vars": {"FOO": "bar"}}
    fields, failure = _dispatch_error(logged, "env_config_fanout")
    assert fields["deployment_id"] == str(ids.b_id)
    assert isinstance(failure, UnresolvableAffinityReferenceError)
    assert failure.error_metadata == _names_tombstoned_a(ids.a_id, _B_TERM_PATH)
    [line] = [
        line
        for line in _logged(log_info)
        if line.startswith("env_config_fanout_dispatched ")
    ]
    counts = _fields(line)
    assert (counts["dispatched"], counts["dispatch_failed"]) == ("1", "1")
    session.expire_all()
    b = await session.get(Deployment, ids.b_id)
    c = await session.get(Deployment, c_id)
    assert b is not None
    assert c is not None
    assert b.active_application_instance_id == b_instance_id
    assert await _task_count(session, ids.b_id) == tasks_before[ids.b_id]
    assert c.active_application_instance_id is not None
    assert c.status == DeploymentState.DEPLOYING
    assert await _task_count(session, c_id) == tasks_before[c_id] + 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_crd")
async def test_cluster_fan_out_fails_b_s_redeploy_when_e_s_term_names_a(
    client: AsyncClient, session: AsyncSession, mocker
) -> None:
    """US4 scenario 2 with E's term: ``updateEnvironment`` that keeps the term is
    refused before anything is saved, so the cluster config fan-out redeploys B with
    E's term. B's redeploy fails with A's last name and is listed as failed to start."""
    ids = await _set_up(client, session, b_names_a=False)
    environment = await session.get(Environment, ids.environment_id)
    assert environment is not None
    cluster_id, e_config = environment.cluster_id, environment.config
    await _tombstone(client, session, ids.a_id)

    refused = await _post(
        client,
        "update_environment",
        {
            "environmentId": str(ids.environment_id),
            "input": {
                "envVars": [{"name": "FOO", "value": "bar"}],
                "scheduling": {
                    "podAntiAffinity": _term_input({"deploymentId": str(ids.a_id)})
                },
            },
        },
    )

    [error] = refused["errors"]
    assert error["extensions"] == {
        "code": "VALIDATION_ERROR",
        **_names_tombstoned_a(ids.a_id, _E_TERM_PATH),
    }
    session.expire_all()
    environment = await session.get(Environment, ids.environment_id)
    assert environment is not None
    assert environment.config == e_config
    tasks_before = await _task_count(session, ids.b_id)
    log_info = mocker.patch.object(cluster_config_fanout.logger, "info")
    logged = _capture_logged_errors(mocker)

    data = await gql(
        client,
        "update_cluster",
        {"clusterId": str(cluster_id), "input": {"fqdnSuffix": "apps.example.com"}},
    )

    result = data["updateCluster"]
    assert result["redeployed"] == []
    assert [entry["deploymentId"] for entry in result["failedToStart"]] == [
        str(ids.b_id)
    ]
    fields, failure = _dispatch_error(logged, "cluster_config_fanout")
    assert fields["deployment_id"] == str(ids.b_id)
    assert isinstance(failure, UnresolvableAffinityReferenceError)
    assert failure.error_metadata == _names_tombstoned_a(ids.a_id, _E_TERM_PATH)
    [line] = [
        line for line in _logged(log_info) if line.startswith("cluster_config_fanout ")
    ]
    assert _fields(line)["dispatch_failed"] == "1"
    session.expire_all()
    assert await _task_count(session, ids.b_id) == tasks_before


@pytest.mark.asyncio
@pytest.mark.usefixtures("patch_crd")
async def test_term_written_again_with_the_name_binds_the_re_created_deployment(
    client: AsyncClient, session: AsyncSession
) -> None:
    """US4 scenario 3: after A is tombstoned, a new deployment named A is deployed with
    another driver. B's term sent again with ``deploymentName: a`` is accepted, stores
    the new A's id, and B's ``resolvedScheduling`` selects the new A."""
    ids = await _set_up(client, session, e_names_a=False)
    await _tombstone(client, session, ids.a_id)
    await seed_application_driver_version(session, driver_name="a-driver-v2")

    deployed = await gql(
        client,
        "deploy",
        {
            "driver": "a-driver-v2",
            "version": "1.0.0",
            "environmentId": str(ids.environment_id),
            "name": "a",
        },
    )
    new_a_id = UUID(deployed["deploy"]["deploymentId"])
    assert new_a_id != ids.a_id

    await gql(
        client,
        "update_deployment",
        {
            "deploymentId": str(ids.b_id),
            "input": {
                "scheduling": {"podAffinity": _term_input({"deploymentName": "a"})}
            },
        },
    )

    b_config, _ = await _configs(client, ids)
    assert b_config == {"scheduling": {"pod_affinity": _stored_term(new_a_id)}}
    [entry] = await _resolved_scheduling(client, ids.b_id)
    [weighted] = entry["config"]["pod_affinity"]["preferred"]
    assert weighted["term"]["label_selector"] == _selector(new_a_id)
    session.expire_all()
    old_a = await session.get(Deployment, ids.a_id)
    assert old_a is not None
    assert (old_a.name, old_a.status) == ("a", DeploymentState.DELETED)
