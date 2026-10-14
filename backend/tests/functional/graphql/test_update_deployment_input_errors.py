"""Error-propagation tests for ``UpdateDeploymentInput`` (011 / T031).

One parametrized test (:func:`test_update_deployment_input_error_code`)
covers every row of the 9-row error matrix in
``specs/011-typed-deployment-input/contracts/graphql.md`` §5. Each row
crafts an ``updateDeployment`` input that triggers exactly one typed
error and asserts:

* the GraphQL response carries ``errors``;
* ``response.errors[0]['extensions']['code']`` matches the expected
  typed code;
* where the matrix promises a payload field (``name`` / ``scope`` /
  ``component_name``), the field is present on ``extensions`` with the
  expected value.

The fixture uses the ``client`` (admin Bearer) so the boundary
``RequiresAuthentication`` extension is fully exercised. The
``prefect_manager_mock`` fixture isn't needed because every row fails
**before** the resolver dispatches anything to the workflow engine —
this is the whole point of typed-error pre-validation (FR-008 / FR-009).

The ``COMPONENT_CONTAINER_NOT_DECLARED`` matrix (017 / FR-003) below also
drives accepted writes, so it arms the Prefect mock.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Component,
    ComponentConfig,
    Deployment,
    Task,
)

from ._queries import load_query
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_deployment_with_components(
    session: AsyncSession,
    *,
    component_names: list[str],
) -> Any:
    """Seed a deployment whose driver declares ``component_names`` and whose
    Component rows mirror those names.
    """
    adv = await seed_application_driver_version(session)
    for name in component_names:
        cc = ComponentConfig(
            name=name,
            config={
                "identifier": {
                    "label": {"app.kubernetes.io/name": f"{name}-app"},
                },
            },
            application_driver_version_id=adv.id,
        )
        session.add(cc)
    await session.commit()
    deployment = await seed_deployment(session, adv=adv)
    for name in component_names:
        comp = Component(
            name=name,
            config={
                "identifier": {
                    "label": {"app.kubernetes.io/name": f"{name}-app"},
                },
            },
            enabled=True,
            deployment_id=deployment.id,
        )
        session.add(comp)
    await session.commit()
    return deployment


# ---------------------------------------------------------------------------
# Error matrix
# ---------------------------------------------------------------------------
#
# Each row is (row_id, build_input, expected_code, expected_metadata,
# needs_driver_components).
#
#  - ``build_input``  is a callable that, given the seeded driver's
#    component names, returns the GraphQL ``input`` variable.
#  - ``expected_code`` is the ``extensions.code`` string the matrix
#    promises.
#  - ``expected_metadata`` is a dict of additional ``extensions`` keys
#    that must equal the given value (e.g. ``{"name": "1invalid"}``).
#  - ``needs_driver_components`` flips the seeding helper to
#    ``_seed_deployment_with_components(["api", "worker"])`` instead of
#    the bare ``seed_deployment`` path.

_OVERSIZED_VALUE = "x" * (64 * 1024 + 1)


def _e1_invalid_env_var_name_top_level(_components: list[str]) -> dict[str, Any]:
    return {"envVars": [{"name": "1invalid", "value": "x"}]}


def _e2_invalid_env_var_name_component(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": components[0],
                "envVars": [{"name": "1invalid", "value": "x"}],
            }
        ]
    }


def _e3_duplicate_env_var_name_top_level(_components: list[str]) -> dict[str, Any]:
    return {
        "envVars": [
            {"name": "FOO", "value": "a"},
            {"name": "FOO", "value": "b"},
        ]
    }


def _e4_duplicate_env_var_name_component(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": components[0],
                "envVars": [
                    {"name": "BAR", "value": "1"},
                    {"name": "BAR", "value": "2"},
                ],
            }
        ]
    }


def _e5_env_var_size_top_level(_components: list[str]) -> dict[str, Any]:
    return {"envVars": [{"name": "BIG", "value": _OVERSIZED_VALUE}]}


def _e6_env_var_size_component(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": components[0],
                "envVars": [{"name": "BIG", "value": _OVERSIZED_VALUE}],
            }
        ]
    }


def _e7_unknown_component(_components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {
                "name": "does_not_exist",
                "envVars": [{"name": "X", "value": "y"}],
            }
        ]
    }


def _e8_duplicate_parameter_name(_components: list[str]) -> dict[str, Any]:
    return {
        "parameters": [
            {"name": "replicas", "value": 1},
            {"name": "replicas", "value": 2},
        ]
    }


def _e9_duplicate_component_name(components: list[str]) -> dict[str, Any]:
    return {
        "components": [
            {"name": components[0], "envVars": [{"name": "X", "value": "y"}]},
            {"name": components[0], "envVars": []},
        ]
    }


_ERROR_ROWS = [
    # (row_id, build_input, expected_code, expected_metadata, needs_driver_components)
    (
        "e1_invalid_env_var_name_top_level",
        _e1_invalid_env_var_name_top_level,
        "INVALID_ENV_VAR_NAME",
        {"name": "1invalid"},
        False,
    ),
    (
        "e2_invalid_env_var_name_component",
        _e2_invalid_env_var_name_component,
        "INVALID_ENV_VAR_NAME",
        {"name": "1invalid", "scope": "component"},
        True,
    ),
    (
        "e3_duplicate_env_var_name_top_level",
        _e3_duplicate_env_var_name_top_level,
        "DUPLICATE_ENV_VAR_NAME",
        {"name": "FOO", "scope": "deployment"},
        False,
    ),
    (
        "e4_duplicate_env_var_name_component",
        _e4_duplicate_env_var_name_component,
        "DUPLICATE_ENV_VAR_NAME",
        # The component scope is encoded as ``component:<name>`` per
        # research.md §4 and the ``_flatten_components`` helper; the
        # seeded fixture's first component is ``"api"`` so the scope
        # reaching the GraphQL extensions payload is ``component:api``.
        # FR-009 mandates the scope reach the boundary intact, so assert
        # on it explicitly. The matcher already does substring-match on
        # the ``scope`` key.
        {"name": "BAR", "scope": "component:api"},
        True,
    ),
    (
        "e5_env_var_size_top_level",
        _e5_env_var_size_top_level,
        "ENV_VAR_SIZE_LIMIT_EXCEEDED",
        {"name": "BIG"},
        False,
    ),
    (
        "e6_env_var_size_component",
        _e6_env_var_size_component,
        "ENV_VAR_SIZE_LIMIT_EXCEEDED",
        {"name": "BIG", "scope": "component"},
        True,
    ),
    (
        "e7_unknown_component",
        _e7_unknown_component,
        "UNKNOWN_COMPONENT_ENV_VAR",
        {"component_name": "does_not_exist"},
        True,
    ),
    (
        "e8_duplicate_parameter_name",
        _e8_duplicate_parameter_name,
        "DUPLICATE_PARAMETER_NAME",
        {"name": "replicas"},
        False,
    ),
    (
        "e9_duplicate_component_name",
        _e9_duplicate_component_name,
        "DUPLICATE_COMPONENT_NAME",
        # The duplicate-component check fires on the second occurrence;
        # the offending name is the seeded fixture's first component
        # ("api"). FR-009 mandates the typed payload identify the
        # offending name.
        {"name": "api"},
        True,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row_id", "build_input", "expected_code", "expected_metadata", "needs_driver"),
    _ERROR_ROWS,
    ids=[row[0] for row in _ERROR_ROWS],
)
async def test_update_deployment_input_error_code(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001 — guards against accidental Prefect dispatch
    row_id: str,
    build_input: Any,
    expected_code: str,
    expected_metadata: dict[str, Any],
    needs_driver: bool,
) -> None:
    """Drive every row of the 9-row error matrix from ``contracts/graphql.md``
    §5: each row submits an input that triggers one typed error and asserts
    on ``response.errors[0]['extensions']['code']`` (and any payload field
    the matrix promises).
    """
    if needs_driver:
        component_names = ["api", "worker"]
        deployment = await _seed_deployment_with_components(
            session, component_names=component_names
        )
    else:
        component_names = []
        deployment = await seed_deployment(session)

    input_var = build_input(component_names)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment.id),
                "input": input_var,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, (
        f"row {row_id}: expected an errors array, got data only: {payload}"
    )
    errors = payload["errors"]
    assert len(errors) >= 1
    extensions = errors[0].get("extensions") or {}
    assert extensions.get("code") == expected_code, (
        f"row {row_id}: expected extensions.code = {expected_code!r}; "
        f"got {extensions.get('code')!r}. Full extensions: {extensions}"
    )
    for key, value in expected_metadata.items():
        actual = extensions.get(key)
        if key == "scope":
            # Some scopes carry a free-form prefix (``component:<name>``);
            # accept either equality or a "starts-with" match so the test
            # is robust to scope-format tweaks across rows.
            assert actual is not None, (
                f"row {row_id}: expected scope, got None in {extensions}"
            )
            assert value in actual, (
                f"row {row_id}: expected scope to contain {value!r}; got {actual!r}"
            )
        else:
            assert actual == value, (
                f"row {row_id}: expected extensions.{key} = {value!r}; "
                f"got {actual!r}. Full extensions: {extensions}"
            )


# ---------------------------------------------------------------------------
# COMPONENT_CONTAINER_NOT_DECLARED (017 / FR-003, research D-007)
# ---------------------------------------------------------------------------
#
# ``api`` declares a component container, ``worker`` declares none. Only
# additions and value changes on ``worker`` are rejected; removals and
# unchanged re-submissions pass so stored values can be cleaned up.

_STORED_WORKER_ENV = {"A": "1", "B": "2"}


def _arm_prefect(prefect_manager_mock: Any) -> None:
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


def _component_config(name: str, container: str | None) -> dict[str, Any]:
    return {
        "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
        "container": container,
    }


async def _add_component_configs(
    session: AsyncSession, adv_id: UUID, containers: dict[str, str | None]
) -> None:
    for name, container in containers.items():
        session.add(
            ComponentConfig(
                name=name,
                config=_component_config(name, container),
                application_driver_version_id=adv_id,
            )
        )
    await session.commit()


async def _seed_container_deployment(
    session: AsyncSession,
    *,
    containers: dict[str, str | None],
    stored_worker_env: dict[str, str] | None,
    adv: ApplicationDriverVersion | None = None,
) -> UUID:
    """Seed a deployment bound to a driver version declaring ``containers``."""
    if adv is None:
        adv = await seed_application_driver_version(session)
        await _add_component_configs(session, adv.id, containers)
    deployment = await seed_deployment(session, adv=adv)
    for name, container in containers.items():
        session.add(
            Component(
                name=name,
                config=_component_config(name, container),
                enabled=True,
                deployment_id=deployment.id,
            )
        )
    if stored_worker_env is not None:
        deployment.config = {"components": {"worker": {"env_vars": stored_worker_env}}}
        session.add(deployment)
    await session.commit()
    return deployment.id


def _worker_input(env: dict[str, str] | None) -> dict[str, Any]:
    row: dict[str, Any] = {"name": "worker"}
    if env is not None:
        row["envVars"] = [{"name": k, "value": v} for k, v in env.items()]
    return {"components": [row]}


async def _post_update(
    client: AsyncClient, deployment_id: UUID, input_var: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {"deploymentId": str(deployment_id), "input": input_var},
        },
    )
    assert response.status_code == 200
    return response.json()


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(rows.all())


async def _stored_config(session: AsyncSession, deployment_id: UUID) -> dict | None:
    session.expire_all()
    row = await session.get(Deployment, deployment_id)
    assert row is not None
    return row.config


def _assert_container_not_declared(
    payload: dict[str, Any], components_with_container: list[str]
) -> None:
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "COMPONENT_CONTAINER_NOT_DECLARED", extensions
    assert extensions.get("component_name") == "worker", extensions
    assert extensions.get("components_with_container") == components_with_container
    assert "'worker'" in payload["errors"][0]["message"]


async def _assert_rejected_without_task(
    session: AsyncSession,
    prefect_manager_mock: Any,
    deployment_id: UUID,
    payload: dict[str, Any],
    *,
    components_with_container: list[str],
    stored_before: dict | None,
    tasks_before: int,
) -> None:
    _assert_container_not_declared(payload, components_with_container)
    prefect_manager_mock.run_action.assert_not_awaited()
    assert await _task_count(session, deployment_id) == tasks_before
    assert await _stored_config(session, deployment_id) == stored_before


_REJECTED_CASES = [
    ("add_key", {**_STORED_WORKER_ENV, "C": "3"}),
    ("change_value", {"A": "1", "B": "changed"}),
]

_ACCEPTED_CASES = [
    ("remove_key", {"A": "1"}),
    ("remove_all", None),
    ("unchanged", dict(_STORED_WORKER_ENV)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "submitted"), _REJECTED_CASES, ids=[c[0] for c in _REJECTED_CASES]
)
async def test_component_container_not_declared_rejects_add_or_change(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    case_id: str,  # noqa: ARG001 — parametrize id
    submitted: dict[str, str],
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_container_deployment(
        session,
        containers={"api": "api-app", "worker": None},
        stored_worker_env=_STORED_WORKER_ENV,
    )
    stored_before = await _stored_config(session, deployment_id)

    payload = await _post_update(client, deployment_id, _worker_input(submitted))

    await _assert_rejected_without_task(
        session,
        prefect_manager_mock,
        deployment_id,
        payload,
        components_with_container=["api"],
        stored_before=stored_before,
        tasks_before=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "submitted"), _ACCEPTED_CASES, ids=[c[0] for c in _ACCEPTED_CASES]
)
async def test_component_container_not_declared_accepts_remove_or_unchanged(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    case_id: str,  # noqa: ARG001 — parametrize id
    submitted: dict[str, str] | None,
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_container_deployment(
        session,
        containers={"api": "api-app", "worker": None},
        stored_worker_env=_STORED_WORKER_ENV,
    )

    payload = await _post_update(client, deployment_id, _worker_input(submitted))

    assert "errors" not in payload, payload
    stored = await _stored_config(session, deployment_id)
    assert stored is not None
    assert stored["components"]["worker"].get("env_vars") == submitted


@pytest.mark.asyncio
async def test_component_container_not_declared_rejects_first_value(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """No stored block: any value on a containerless component is an addition."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_container_deployment(
        session,
        containers={"api": "api-app", "worker": None},
        stored_worker_env=None,
    )

    payload = await _post_update(client, deployment_id, _worker_input({"A": "1"}))

    await _assert_rejected_without_task(
        session,
        prefect_manager_mock,
        deployment_id,
        payload,
        components_with_container=["api"],
        stored_before=None,
        tasks_before=0,
    )


@pytest.mark.asyncio
async def test_component_container_not_declared_treats_missing_key_as_none(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Component config rows stored before 017 carry no ``container`` key."""
    _arm_prefect(prefect_manager_mock)
    adv = await seed_application_driver_version(session)
    session.add(
        ComponentConfig(
            name="worker",
            config={"identifier": {"label": {"app.kubernetes.io/name": "worker-app"}}},
            application_driver_version_id=adv.id,
        )
    )
    await session.commit()
    deployment_id = await _seed_container_deployment(
        session, containers={"worker": None}, stored_worker_env=None, adv=adv
    )

    payload = await _post_update(client, deployment_id, _worker_input({"A": "1"}))

    _assert_container_not_declared(payload, components_with_container=[])
    prefect_manager_mock.run_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_component_container_not_declared_allows_broader_scopes(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Deployment-scope env vars skip containerless components (US4 Sc.3)."""
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_container_deployment(
        session,
        containers={"api": "api-app", "worker": None},
        stored_worker_env=None,
    )

    payload = await _post_update(
        client, deployment_id, {"envVars": [{"name": "LOG_LEVEL", "value": "debug"}]}
    )

    assert "errors" not in payload, payload
    stored = await _stored_config(session, deployment_id)
    assert stored is not None
    assert stored["env_vars"] == {"LOG_LEVEL": "debug"}


@pytest.mark.asyncio
async def test_component_container_declared_accepts_new_value(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_container_deployment(
        session,
        containers={"api": "api-app", "worker": "worker-app"},
        stored_worker_env=None,
    )

    payload = await _post_update(client, deployment_id, _worker_input({"A": "1"}))

    assert "errors" not in payload, payload
    stored = await _stored_config(session, deployment_id)
    assert stored is not None
    assert stored["components"]["worker"]["env_vars"] == {"A": "1"}


# -- Validated against the driver version the deployment is pinned to --------
#
# ``updateDeployment`` carries no driver version; the version switch is
# ``updateDeploymentVersion``. After a switch, writes are validated against the
# newly pinned version, not the one the stored values were written under.


async def _seed_switch(
    session: AsyncSession,
    *,
    before: dict[str, str | None],
    after: dict[str, str | None],
    stored_worker_env: dict[str, str] | None,
) -> tuple[UUID, UUID]:
    """Seed two versions of one driver; the deployment is bound to the first."""
    old = await seed_application_driver_version(session, version="1.0.0")
    driver = await session.get(ApplicationDriver, old.application_driver_id)
    assert driver is not None
    new = await seed_application_driver_version(session, driver=driver, version="2.0.0")
    await _add_component_configs(session, old.id, before)
    await _add_component_configs(session, new.id, after)
    new_id = new.id
    deployment_id = await _seed_container_deployment(
        session, containers=before, stored_worker_env=stored_worker_env, adv=old
    )
    return deployment_id, new_id


async def _switch_driver_version(
    client: AsyncClient, deployment_id: UUID, driver_version_id: UUID
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_version"),
            "variables": {
                "deploymentId": str(deployment_id),
                "version": "1.0.0",
                "driverVersionId": str(driver_version_id),
            },
        },
    )
    assert response.status_code == 200
    assert "errors" not in response.json(), response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "submitted"), _REJECTED_CASES, ids=[c[0] for c in _REJECTED_CASES]
)
async def test_component_container_lost_on_switch_rejects_add_or_change(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    case_id: str,  # noqa: ARG001 — parametrize id
    submitted: dict[str, str],
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_id = await _seed_switch(
        session,
        before={"api": "api-app", "worker": "worker-app"},
        after={"api": "api-app", "worker": None},
        stored_worker_env=_STORED_WORKER_ENV,
    )
    await _switch_driver_version(client, deployment_id, new_id)
    stored_before = await _stored_config(session, deployment_id)
    tasks_before = await _task_count(session, deployment_id)
    prefect_manager_mock.run_action.reset_mock()

    payload = await _post_update(client, deployment_id, _worker_input(submitted))

    await _assert_rejected_without_task(
        session,
        prefect_manager_mock,
        deployment_id,
        payload,
        components_with_container=["api"],
        stored_before=stored_before,
        tasks_before=tasks_before,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "submitted"), _ACCEPTED_CASES, ids=[c[0] for c in _ACCEPTED_CASES]
)
async def test_component_container_lost_on_switch_accepts_remove_or_unchanged(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    case_id: str,  # noqa: ARG001 — parametrize id
    submitted: dict[str, str] | None,
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_id = await _seed_switch(
        session,
        before={"api": "api-app", "worker": "worker-app"},
        after={"api": "api-app", "worker": None},
        stored_worker_env=_STORED_WORKER_ENV,
    )
    await _switch_driver_version(client, deployment_id, new_id)
    # The switch itself keeps the stored values (FR-005).
    stored = await _stored_config(session, deployment_id)
    assert stored is not None
    assert stored["components"]["worker"]["env_vars"] == _STORED_WORKER_ENV

    payload = await _post_update(client, deployment_id, _worker_input(submitted))

    assert "errors" not in payload, payload
    stored = await _stored_config(session, deployment_id)
    assert stored is not None
    assert stored["components"]["worker"].get("env_vars") == submitted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "submitted"),
    _REJECTED_CASES + _ACCEPTED_CASES,
    ids=[c[0] for c in _REJECTED_CASES + _ACCEPTED_CASES],
)
async def test_component_container_gained_on_switch_accepts_every_write(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    case_id: str,  # noqa: ARG001 — parametrize id
    submitted: dict[str, str] | None,
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, new_id = await _seed_switch(
        session,
        before={"api": "api-app", "worker": None},
        after={"api": "api-app", "worker": "worker-app"},
        stored_worker_env=_STORED_WORKER_ENV,
    )
    # Before the switch the pinned version has no container for ``worker``.
    pre_switch = await _post_update(
        client, deployment_id, _worker_input({**_STORED_WORKER_ENV, "C": "3"})
    )
    _assert_container_not_declared(pre_switch, components_with_container=["api"])

    await _switch_driver_version(client, deployment_id, new_id)
    payload = await _post_update(client, deployment_id, _worker_input(submitted))

    assert "errors" not in payload, payload
    stored = await _stored_config(session, deployment_id)
    assert stored is not None
    assert stored["components"]["worker"].get("env_vars") == submitted


# -- deploy (create) ------------------------------------------------------------


async def _deploy_with_worker_env(
    client: AsyncClient,
    session: AsyncSession,
    containers: dict[str, str | None],
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session, version="1.0.0")
    await _add_component_configs(session, adv.id, containers)
    driver = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver is not None
    name = f"cc-{uuid4().hex[:8]}"
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver.name,
                "environmentId": str(environment.id),
                "version": "1.0.0",
                "name": name,
                "config": config or _worker_input({"A": "1"}),
            },
        },
    )
    assert response.status_code == 200
    return response.json(), name


@pytest.mark.asyncio
async def test_deploy_rejects_component_env_var_without_container(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)

    payload, name = await _deploy_with_worker_env(
        client, session, {"api": "api-app", "worker": None}
    )

    _assert_container_not_declared(payload, components_with_container=["api"])
    prefect_manager_mock.run_action.assert_not_awaited()
    created = await session.exec(select(Deployment).where(Deployment.name == name))
    assert created.first() is None


@pytest.mark.asyncio
async def test_deploy_accepts_component_env_var_with_container(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)

    payload, name = await _deploy_with_worker_env(
        client, session, {"api": "api-app", "worker": "worker-app"}
    )

    assert "errors" not in payload, payload
    session.expire_all()
    created = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    assert created.config["components"]["worker"]["env_vars"] == {"A": "1"}


# -- Container command and args (022 FR-007, research D-005) -------------------
#
# ``command`` and ``args`` follow the image rule: a submitted list that differs
# from the stored one is rejected on ``worker``; a removal (``null`` or an
# omitted key) and the stored list sent again are accepted.

_STORED_WORKER_LIST = ["--port", "8000"]
_LIST_FIELDS = ["command", "args"]
_OMIT = object()


async def _store_worker_block(
    session: AsyncSession, deployment_id: UUID, block: dict[str, Any]
) -> dict | None:
    row = await session.get(Deployment, deployment_id)
    assert row is not None
    row.config = {"components": {"worker": block}}
    session.add(row)
    await session.commit()
    return await _stored_config(session, deployment_id)


def _assert_list_override_not_declared(payload: dict[str, Any], field: str) -> None:
    _assert_container_not_declared(payload, components_with_container=["api"])
    error = payload["errors"][0]
    assert error["extensions"].get("override") == field, error
    assert error["message"].startswith(
        f"Container {field} override targets component 'worker'"
    ), error


@pytest.mark.asyncio
@pytest.mark.parametrize("field", _LIST_FIELDS)
@pytest.mark.parametrize(
    ("stored", "submitted"),
    [
        (None, ["--debug"]),
        (_STORED_WORKER_LIST, ["--port", "9000"]),
    ],
    ids=["add", "change"],
)
async def test_component_container_not_declared_rejects_command_args_add_or_change(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    field: str,
    stored: list[str] | None,
    submitted: list[str],
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_container_deployment(
        session, containers={"api": "api-app", "worker": None}, stored_worker_env=None
    )
    stored_before = (
        await _store_worker_block(session, deployment_id, {field: stored})
        if stored is not None
        else None
    )

    payload = await _post_update(
        client,
        deployment_id,
        {"components": [{"name": "worker", field: submitted}]},
    )

    _assert_list_override_not_declared(payload, field)
    await _assert_rejected_without_task(
        session,
        prefect_manager_mock,
        deployment_id,
        payload,
        components_with_container=["api"],
        stored_before=stored_before,
        tasks_before=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", _LIST_FIELDS)
@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        (None, None),
        (_OMIT, None),
        (_STORED_WORKER_LIST, _STORED_WORKER_LIST),
    ],
    ids=["remove-null", "remove-omitted", "unchanged"],
)
async def test_component_container_not_declared_accepts_command_args_remove_or_unchanged(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    field: str,
    submitted: object,
    expected: list[str] | None,
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id = await _seed_container_deployment(
        session, containers={"api": "api-app", "worker": None}, stored_worker_env=None
    )
    await _store_worker_block(session, deployment_id, {field: _STORED_WORKER_LIST})
    component: dict[str, Any] = {"name": "worker"}
    if submitted is not _OMIT:
        component[field] = submitted

    payload = await _post_update(client, deployment_id, {"components": [component]})

    assert "errors" not in payload, payload
    stored = await _stored_config(session, deployment_id) or {}
    worker = (stored.get("components") or {}).get("worker") or {}
    assert worker.get(field) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("field", _LIST_FIELDS)
async def test_deploy_rejects_component_command_args_without_container(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    field: str,
) -> None:
    _arm_prefect(prefect_manager_mock)

    payload, name = await _deploy_with_worker_env(
        client,
        session,
        {"api": "api-app", "worker": None},
        config={"components": [{"name": "worker", field: ["--debug"]}]},
    )

    _assert_list_override_not_declared(payload, field)
    prefect_manager_mock.run_action.assert_not_awaited()
    created = await session.exec(select(Deployment).where(Deployment.name == name))
    assert created.first() is None
