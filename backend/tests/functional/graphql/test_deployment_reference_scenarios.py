"""A rename leaves the affinity terms that name the deployment working (027 US1, #492).

Environment E has deployments A and B. B's config has a pod affinity term and E's
config has a pod anti-affinity term, both written with ``deploymentName: a``. Before
027 the rename of A was refused, because it built A's new instance with E's term and
looked the old name up. The terms now store A's id, so the rename and every later
update and config fan-out redeploy succeed.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Component, Deployment, Task
from styrmin_backend.services import cluster_config_fanout

from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

_TOPOLOGY_KEY = "kubernetes.io/hostname"


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())
    return prefect_manager_mock


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


async def _set_up(client: AsyncClient, session: AsyncSession) -> _Environment:
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
    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(ids.environment_id),
            "input": {
                "scheduling": {"podAntiAffinity": _term_input({"deploymentName": "a"})}
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
