"""Propagation tests for the no-op detection behaviour of the deployment
update mutations (spec 014 / ``contracts/graphql.md``).

These tests pin the *behavioural* contract at the GraphQL ↔ DB boundary:

1. ``updateDeployment`` no-op → ``null``; DB ``ApplicationInstance`` count,
   the deployment's active-instance pointer, and its status are unchanged.
2. ``updateDeployment`` real config change → non-null ``Task`` + exactly one
   new ``ApplicationInstance``.
3. ``updateDeployment`` empty/no-op input → ``null`` (NOT an
   ``INVALID_CONTEXT`` / ``VALIDATION_ERROR`` error — the "at least one of
   config…" guard was removed in spec 014 phase A).
4. ``updateDeploymentVersion`` same version → ``null``; no new instance/task.
5. ``updateDeploymentVersion`` new version → non-null ``Task``.
6. A config with an affinity term, read back and written with ``updateDeployment``
   → ``null`` (027 US8 scenario 1).
7. ``updateDeploymentVersion`` re-sending a term whose deployment reference gives
   the name, as ``deployments apply`` does → ``null`` (027 US8 scenario 2).
8. ``updateEnvironment`` re-sending such a term → every deployment is skipped as
   already at config.

Each test drives a *first* update through the real mutation to establish an
active instance (so the candidate generated on the re-apply has a current
instance to compare against), then exercises the no-op / change path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession
from styrmin_sdk.models import UpdateDeploymentInput

from styrmin_backend.db.models import ApplicationInstance, Deployment, Task
from styrmin_backend.services import environments

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

_TOPOLOGY_KEY = "kubernetes.io/hostname"


def _flow_info_factory() -> AsyncMock:
    """An ``AsyncMock`` for ``run_action`` that returns a fresh flow-info
    object (with a real UUID ``id``) on every call, so the dispatched
    ``Task.prefect_flow_run_id`` binds to a bindable value rather than a
    mock attribute."""

    async def _run(*_args, **_kwargs):
        return type("FlowInfo", (), {"id": uuid4()})()

    return AsyncMock(side_effect=_run)


async def _instance_count(session: AsyncSession, deployment_id) -> int:
    result = await session.exec(
        select(ApplicationInstance).where(
            ApplicationInstance.deployment_id == deployment_id
        )
    )
    return len(result.all())


async def _update_deployment(
    client: AsyncClient, deployment_id, input_var: dict
) -> dict:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {"deploymentId": str(deployment_id), "input": input_var},
        },
    )
    assert response.status_code == 200
    return response.json()


async def _update_version(client: AsyncClient, deployment_id, version: str) -> dict:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_version"),
            "variables": {"deploymentId": str(deployment_id), "version": version},
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_update_deployment_noop_returns_null_db_unchanged(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Re-applying an identical config resolves to the current instance:
    the mutation returns ``null`` and leaves the instance count, the
    active-instance pointer, and the deployment status untouched."""
    prefect_manager_mock.run_action = _flow_info_factory()
    deployment = await seed_deployment(session)
    deployment_id = deployment.id
    config = {"ipWhitelist": ["10.0.0.0/8"]}

    # First apply establishes an active instance + task.
    first = await _update_deployment(client, deployment_id, config)
    assert "errors" not in first, first
    assert first["data"]["updateDeployment"] is not None

    session.expire_all()
    refreshed = await session.get(Deployment, deployment_id)
    assert refreshed is not None
    active_before = refreshed.active_application_instance_id
    status_before = refreshed.status
    assert active_before is not None
    count_before = await _instance_count(session, deployment_id)
    assert count_before == 1

    # Re-applying the identical config is a no-op.
    second = await _update_deployment(client, deployment_id, config)
    assert "errors" not in second, second
    assert second["data"]["updateDeployment"] is None

    session.expire_all()
    after = await session.get(Deployment, deployment_id)
    assert after is not None
    assert after.active_application_instance_id == active_before
    assert after.status == status_before
    assert await _instance_count(session, deployment_id) == count_before


@pytest.mark.asyncio
async def test_update_deployment_real_change_returns_task_and_new_instance(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A genuine config change returns a non-null Task and persists exactly
    one new ApplicationInstance."""
    prefect_manager_mock.run_action = _flow_info_factory()
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    first = await _update_deployment(
        client, deployment_id, {"ipWhitelist": ["10.0.0.0/8"]}
    )
    assert "errors" not in first, first
    assert first["data"]["updateDeployment"] is not None
    count_before = await _instance_count(session, deployment_id)
    assert count_before == 1

    second = await _update_deployment(
        client, deployment_id, {"ipWhitelist": ["192.168.0.0/16"]}
    )
    assert "errors" not in second, second
    assert second["data"]["updateDeployment"] is not None
    assert await _instance_count(session, deployment_id) == count_before + 1


@pytest.mark.asyncio
async def test_update_deployment_adding_previously_absent_field_is_a_change(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Regression (spec 014): ADDING a previously-absent config field must be
    treated as a change, not a no-op.

    The first update carries empty config, establishing an active instance
    whose resolved context has no ip-whitelist. The second update *adds* one —
    a transition DeepDiff classifies as ``type_changes`` (``None`` → value) /
    ``dictionary_item_added``, NOT ``values_changed``. The no-op gate must
    detect it via the raw structural diff and dispatch a reconcile; the prior
    serializer-based ``diff is None`` check missed this and silently dropped
    the change."""
    prefect_manager_mock.run_action = _flow_info_factory()
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    # First update establishes an active instance with NO ip-whitelist.
    first = await _update_deployment(client, deployment_id, {})
    assert "errors" not in first, first
    count_before = await _instance_count(session, deployment_id)
    assert count_before == 1

    # Adding a previously-absent field is a real change → task + new instance.
    second = await _update_deployment(
        client, deployment_id, {"ipWhitelist": ["10.0.0.0/8"]}
    )
    assert "errors" not in second, second
    assert second["data"]["updateDeployment"] is not None
    assert await _instance_count(session, deployment_id) == count_before + 1


@pytest.mark.asyncio
async def test_update_deployment_empty_input_returns_null_not_error(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """An effectively-empty input resolves to no change → ``null``, NOT an
    ``INVALID_CONTEXT`` / ``VALIDATION_ERROR`` error (the guard was removed
    in spec 014 phase A)."""
    prefect_manager_mock.run_action = _flow_info_factory()
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    # Establish an active instance so the empty re-apply has a baseline.
    first = await _update_deployment(
        client, deployment_id, {"ipWhitelist": ["10.0.0.0/8"]}
    )
    assert "errors" not in first, first
    count_before = await _instance_count(session, deployment_id)

    payload = await _update_deployment(client, deployment_id, {})
    assert "errors" not in payload, payload
    assert payload["data"]["updateDeployment"] is None
    assert await _instance_count(session, deployment_id) == count_before


@pytest.mark.asyncio
async def test_update_deployment_version_same_version_returns_null(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Requesting the deployment's current version (no other change) is a
    no-op: ``null``, no new instance, no task."""
    prefect_manager_mock.run_action = _flow_info_factory()
    deployment = await seed_deployment(session)
    deployment_id = deployment.id
    current_version = deployment.application_version

    # Establish an active instance via a first version update.
    first = await _update_version(client, deployment_id, current_version)
    assert "errors" not in first, first
    assert first["data"]["updateDeploymentVersion"] is not None
    count_before = await _instance_count(session, deployment_id)
    assert count_before == 1

    session.expire_all()
    refreshed = await session.get(Deployment, deployment_id)
    assert refreshed is not None
    active_before = refreshed.active_application_instance_id
    status_before = refreshed.status

    second = await _update_version(client, deployment_id, current_version)
    assert "errors" not in second, second
    assert second["data"]["updateDeploymentVersion"] is None

    session.expire_all()
    after = await session.get(Deployment, deployment_id)
    assert after is not None
    assert after.active_application_instance_id == active_before
    assert after.status == status_before
    assert await _instance_count(session, deployment_id) == count_before


@pytest.mark.asyncio
async def test_update_deployment_version_new_version_returns_task(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A different version is an upgrade: returns a non-null Task."""
    prefect_manager_mock.run_action = _flow_info_factory()
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    first = await _update_version(client, deployment_id, "1.0.0")
    assert "errors" not in first, first
    count_before = await _instance_count(session, deployment_id)
    assert count_before == 1

    second = await _update_version(client, deployment_id, "1.0.1")
    assert "errors" not in second, second
    assert second["data"]["updateDeploymentVersion"] is not None
    assert await _instance_count(session, deployment_id) == count_before + 1


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


async def _seed_a_and_b(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    """Environment E with deployments ``a`` and ``b``; returns E's, A's and B's ids."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session)
    a = await seed_deployment(session, environment=environment, adv=adv, name="a")
    b = await seed_deployment(session, environment=environment, adv=adv, name="b")
    return environment.id, a.id, b.id


async def _stored_config(client: AsyncClient, deployment_id: UUID) -> dict[str, Any]:
    data = await gql(
        client, "get_deployment_config", {"deploymentId": str(deployment_id)}
    )
    return data["deployment"]["config"]


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(rows.all())


async def _update_version_with_input(
    client: AsyncClient, deployment_id: UUID, version: str, input_var: dict
) -> dict:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_version_with_input"),
            "variables": {
                "deploymentId": str(deployment_id),
                "version": version,
                "input": input_var,
            },
        },
    )
    assert response.status_code == 200
    return response.json()


def _fan_out_lines(log_info: MagicMock) -> list[dict[str, str]]:
    """The fields of each ``env_config_fanout_dispatched`` line, in order."""
    lines = [
        call.args[0].format(*call.args[1:])
        for call in log_info.call_args_list
        if call.args
    ]
    return [
        dict(part.split("=", 1) for part in line.split()[1:])
        for line in lines
        if line.startswith("env_config_fanout_dispatched ")
    ]


@pytest.mark.asyncio
async def test_update_deployment_writing_back_a_read_term_returns_null(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """027 US8 scenario 1 / FR-009: B's config, read from ``Deployment.config`` and
    written back unchanged, is a no-op although the term was written with A's name."""
    prefect_manager_mock.run_action = _flow_info_factory()
    _, a_id, b_id = await _seed_a_and_b(session)
    first = await _update_deployment(
        client,
        b_id,
        {"scheduling": {"podAffinity": _term_input({"deploymentName": "a"})}},
    )
    assert "errors" not in first, first
    assert first["data"]["updateDeployment"] is not None
    stored = await _stored_config(client, b_id)
    assert stored == {"scheduling": {"pod_affinity": _stored_term(a_id)}}
    instances_before = await _instance_count(session, b_id)
    tasks_before = await _task_count(session, b_id)

    # The SDK model takes the snake_case read and sends the camelCase input.
    written_back = UpdateDeploymentInput.model_validate(stored).model_dump(
        by_alias=True, exclude_none=True
    )
    second = await _update_deployment(client, b_id, written_back)

    assert "errors" not in second, second
    assert second["data"]["updateDeployment"] is None
    session.expire_all()
    assert await _instance_count(session, b_id) == instances_before
    assert await _task_count(session, b_id) == tasks_before
    assert await _stored_config(client, b_id) == stored


@pytest.mark.asyncio
async def test_update_deployment_version_re_sending_a_term_with_the_name_returns_null(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """027 US8 scenario 2 / SC-004: ``deployments apply`` sends the manifest's config
    with the same version through ``updateDeploymentVersion(input:)``. Sent again, the
    term that gives A's name compares equal to the stored term that gives A's id."""
    prefect_manager_mock.run_action = _flow_info_factory()
    _, a_id, b_id = await _seed_a_and_b(session)
    manifest_input = {
        "scheduling": {"podAffinity": _term_input({"deploymentName": "a"})}
    }
    first = await _update_version_with_input(client, b_id, "1.0.0", manifest_input)
    assert "errors" not in first, first
    assert first["data"]["updateDeploymentVersion"] is not None
    stored = await _stored_config(client, b_id)
    assert stored == {"scheduling": {"pod_affinity": _stored_term(a_id)}}
    instances_before = await _instance_count(session, b_id)
    tasks_before = await _task_count(session, b_id)

    second = await _update_version_with_input(client, b_id, "1.0.0", manifest_input)

    assert "errors" not in second, second
    assert second["data"]["updateDeploymentVersion"] is None
    session.expire_all()
    assert await _instance_count(session, b_id) == instances_before
    assert await _task_count(session, b_id) == tasks_before
    assert await _stored_config(client, b_id) == stored


@pytest.mark.asyncio
async def test_update_environment_re_sending_a_term_with_the_name_skips_every_deployment(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock, mocker
) -> None:
    """027 FR-009: E's config re-sent with the term that gives A's name is the stored
    config, so the fan-out finds A and B already at config and redeploys neither."""
    prefect_manager_mock.run_action = _flow_info_factory()
    environment_id, a_id, b_id = await _seed_a_and_b(session)
    environment_input = {
        "scheduling": {"podAntiAffinity": _term_input({"deploymentName": "a"})}
    }
    log_info = mocker.patch.object(environments.logger, "info")
    variables = {"environmentId": str(environment_id), "input": environment_input}

    await gql(client, "update_environment", variables)
    tasks_before = {d: await _task_count(session, d) for d in (a_id, b_id)}
    await gql(client, "update_environment", variables)

    first, second = _fan_out_lines(log_info)
    assert first["dispatched"] == "2"
    assert second["evaluated"] == "2"
    assert second["skipped_noop"] == "2"
    assert second["dispatched"] == "0"
    session.expire_all()
    assert {d: await _task_count(session, d) for d in (a_id, b_id)} == tasks_before
    data = await gql(
        client, "get_environment_config", {"environmentId": str(environment_id)}
    )
    assert data["environment"]["config"] == {
        "scheduling": {"pod_anti_affinity": _stored_term(a_id)}
    }
