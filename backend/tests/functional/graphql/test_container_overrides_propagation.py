"""GraphQL ↔ DB propagation tests for container `command`/`args` overrides (014).

Per Constitution §V every new GraphQL field requires a propagation test that
proves the value flows through the **real** service + repository layers between
the GraphQL boundary and the DB. This module covers:

* the write path through ``updateDeployment(input: { components: [...] })``,
  proving ``command``/``args`` land in ``Deployment.config["components"][name]``
  and project back through ``Deployment.componentContainerOverrides``;
* the create path through the ``deploy`` mutation's ``config`` JSON (FR-002 —
  overrides submitted at create time are handled identically);
* clear semantics (US3), independence (US2), rejection (US4), and orphan
  visibility (US5) are added by their respective phases below.

The single propagation file is created here (US1) and extended in place by
US2–US6 per ``tasks.md``.

The ``updateDeployment`` / ``deploy`` success path regenerates the application
instance and dispatches a reconcile action through the Prefect manager. The
default ``prefect_manager_mock`` returns ``AsyncMock`` sentinels that poison the
DB bind, so every test that drives a *successful* mutation arms the manager
with concrete return values via :func:`_arm_prefect` (mirrors
``test_update_deployment_input_propagation.py``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    Component,
    ComponentConfig,
    Deployment,
)

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Give the Prefect manager concrete (non-AsyncMock) return values so a
    successful ``updateDeployment`` / ``deploy`` reconcile dispatch does not
    leak an ``AsyncMock`` into a DB-bound column.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


async def _seed_deployment_with_components(
    session: AsyncSession,
    *,
    component_names: list[str],
) -> Deployment:
    """Seed a deployment whose driver declares ``component_names`` and whose
    Component rows mirror those names (the deployment-side driver-component map
    the resolver and write-side validation use). Mirrors the helper in
    ``test_env_vars_propagation.py``.
    """
    adv = await seed_application_driver_version(session)
    for name in component_names:
        cc = ComponentConfig(
            name=name,
            config={
                "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
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
                "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
            },
            enabled=True,
            deployment_id=deployment.id,
        )
        session.add(comp)
    await session.commit()
    return deployment


async def _update(
    client: AsyncClient, deployment_id: str, components: list[dict]
) -> dict:
    """Drive ``updateDeployment`` with a typed ``components`` list, asserting
    success (no GraphQL errors). Returns the parsed JSON payload."""
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": deployment_id,
                "input": {"components": components},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    return payload


async def _update_expect_error(
    client: AsyncClient, deployment_id: str, components: list[dict]
) -> dict:
    """Drive ``updateDeployment`` expecting a GraphQL error; return the payload."""
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": deployment_id,
                "input": {"components": components},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    return payload


async def _read_overrides(client: AsyncClient, deployment_id: str) -> dict[str, dict]:
    data = await gql(
        client,
        "get_deployment_component_container_overrides",
        {"deploymentId": deployment_id},
    )
    return {
        row["component"]: row
        for row in data["deployment"]["componentContainerOverrides"]
    }


# ---------------------------------------------------------------------------
# US1 — updateDeployment write → DB → componentContainerOverrides round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_deployment_args_round_trip(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """``updateDeployment`` with ``components: [{name, args}]`` → assert the
    persisted ``config["components"]["server"]["args"]`` equals the input and
    ``componentContainerOverrides`` projects it back (US1, FR-001).
    """
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, component_names=["server", "db"]
    )
    deployment_id = deployment.id
    args = ["--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]

    await _update(client, str(deployment_id), [{"name": "server", "args": args}])

    # Prove the value reached the DB through the real service + repository.
    # Re-query via a fresh SELECT (not ``session.get`` on the stale identity-map
    # object, which would trigger a sync expired-attribute reload).
    session.expire_all()
    db_row = (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()
    assert db_row.config["components"]["server"]["args"] == args
    # No command was submitted → the key must be absent from the persisted block.
    assert "command" not in db_row.config["components"]["server"]

    rows = await _read_overrides(client, str(deployment_id))
    assert "server" in rows
    assert rows["server"]["args"] == args
    assert rows["server"]["command"] is None
    assert rows["server"]["isOrphaned"] is False
    # ``db`` has no override → omitted from the tidy read surface.
    assert "db" not in rows


@pytest.mark.asyncio
async def test_component_container_overrides_empty_when_unset(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A deployment with no override blocks surfaces an empty list."""
    deployment = await _seed_deployment_with_components(
        session, component_names=["server"]
    )
    rows = await _read_overrides(client, str(deployment.id))
    assert rows == {}


@pytest.mark.asyncio
async def test_deploy_create_persists_command_args(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """The ``deploy`` (create) mutation carries ``command``/``args`` inside its
    ``config`` JSON under ``components[<name>]`` and persists them identically
    to the update path (FR-002 covers both flows).

    Drives the real ``deploy_application`` service. Asserts on the persisted
    ``Deployment.config`` of the newly created deployment.
    """
    _arm_prefect(prefect_manager_mock)
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session, version="1.0.0")
    cc = ComponentConfig(
        name="server",
        config={"identifier": {"label": {"app.kubernetes.io/name": "server-app"}}},
        application_driver_version_id=adv.id,
    )
    session.add(cc)
    await session.commit()
    driver_row = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver_row is not None
    driver_name = driver_row.name

    args = ["--host", "0.0.0.0", "--port", "8000"]
    command = ["uvicorn", "simple_app.main:app"]
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver_name,
                "environmentId": str(environment.id),
                "version": "1.0.0",
                "name": "co-create",
                # ``deploy``'s ``config: DeploymentConfigInput`` now shares the
                # same typed list shape as ``updateDeployment``: ``components``
                # is a list of ``{name, command?, args?, env_vars?}`` rows,
                # flattened resolver-side to the persisted dict-keyed-by-name.
                "config": {
                    "components": [{"name": "server", "command": command, "args": args}]
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    created = (
        await session.exec(select(Deployment).where(Deployment.name == "co-create"))
    ).one()
    # ``deploy`` stores the config JSON verbatim under components[<name>].
    assert created.config["components"]["server"]["command"] == command
    assert created.config["components"]["server"]["args"] == args


# ---------------------------------------------------------------------------
# US2 — command and args are independent parallel slots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_and_args_independent(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Setting ``command`` alongside ``args`` persists both as independent
    slots; the read surface projects both (US2, FR-001/FR-007)."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, component_names=["server"]
    )
    deployment_id = deployment.id
    command = ["uvicorn", "simple_app.main:app"]
    args = ["--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]

    await _update(
        client,
        str(deployment_id),
        [{"name": "server", "command": command, "args": args}],
    )

    session.expire_all()
    db_row = (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()
    assert db_row.config["components"]["server"]["command"] == command
    assert db_row.config["components"]["server"]["args"] == args

    rows = await _read_overrides(client, str(deployment_id))
    assert rows["server"]["command"] == command
    assert rows["server"]["args"] == args
    assert rows["server"]["isOrphaned"] is False


# ---------------------------------------------------------------------------
# US3 — clearing a slot under full-replacement (omit = clear)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_args_keeps_command(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Omitting ``args`` under full-replacement clears it while ``command``
    persists; the cleared slot is absent from the persisted block and reads
    back as ``null`` (US3 Sc.2/Sc.3, FR-007)."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, component_names=["server"]
    )
    deployment_id = deployment.id
    command = ["uvicorn", "simple_app.main:app"]

    # Set both, then re-submit with only command → args is cleared.
    await _update(
        client,
        str(deployment_id),
        [{"name": "server", "command": command, "args": ["--port", "8000"]}],
    )
    await _update(client, str(deployment_id), [{"name": "server", "command": command}])

    session.expire_all()
    db_row = (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()
    block = db_row.config["components"]["server"]
    assert block["command"] == command
    assert "args" not in block

    rows = await _read_overrides(client, str(deployment_id))
    assert rows["server"]["command"] == command
    assert rows["server"]["args"] is None


@pytest.mark.asyncio
async def test_clear_all_overrides(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """Submitting the component block with neither slot clears the override
    entirely — the component drops off the tidy read surface (US3)."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, component_names=["server"]
    )
    deployment_id = deployment.id

    await _update(client, str(deployment_id), [{"name": "server", "args": ["--x"]}])
    await _update(client, str(deployment_id), [{"name": "server"}])

    rows = await _read_overrides(client, str(deployment_id))
    assert "server" not in rows


# ---------------------------------------------------------------------------
# US4 — write-boundary rejection (update + deploy call sites)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_rejects_unknown_component(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001 — guards against Prefect dispatch
) -> None:
    """An override targeting an undeclared component is rejected with
    ``UNKNOWN_COMPONENT_CONTAINER_OVERRIDE`` listing the known components;
    no write occurs (US4 Sc.1, FR-004)."""
    deployment = await _seed_deployment_with_components(
        session, component_names=["server", "db"]
    )
    deployment_id = deployment.id
    payload = await _update_expect_error(
        client, str(deployment_id), [{"name": "ghost", "args": ["--x"]}]
    )
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "UNKNOWN_COMPONENT_CONTAINER_OVERRIDE"
    assert extensions.get("component_name") == "ghost"
    assert sorted(extensions.get("known_components") or []) == ["db", "server"]

    # No write occurred — the deployment config stays empty.
    session.expire_all()
    db_row = (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()
    assert not (db_row.config or {}).get("components")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("command", "INVALID_CONTAINER_COMMAND"),
        ("args", "INVALID_CONTAINER_ARGS"),
    ],
)
async def test_update_rejects_empty_list(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001
    field: str,
    code: str,
) -> None:
    """An empty list is rejected per-field at the write boundary (US4 Sc.2,
    FR-006). ``[]`` is a valid ``[String!]`` GraphQL value so it reaches the
    service validator (unlike a non-string element, which GraphQL's
    ``[String!]`` coercion rejects earlier — see the deploy-path test)."""
    deployment = await _seed_deployment_with_components(
        session, component_names=["server"]
    )
    payload = await _update_expect_error(
        client, str(deployment.id), [{"name": "server", field: []}]
    )
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command", [123]),
        ("args", ["ok", 5]),
    ],
)
async def test_deploy_create_rejects_non_string_element(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001
    field: str,
    value: list,
) -> None:
    """A non-string ``command`` / ``args`` element is rejected at the GraphQL
    coercion boundary on the create path.

    Previously the ``deploy`` mutation took a freeform ``JSON`` config and the
    per-field typed error (``INVALID_CONTAINER_COMMAND`` /
    ``INVALID_CONTAINER_ARGS``) fired inside the Pydantic field validator.
    With ``deploy`` now sharing the typed ``DeploymentConfigInput`` (009),
    ``command`` / ``args`` are typed ``[String!]`` and GraphQL's scalar
    coercion rejects a non-string element before any resolver runs — same
    behaviour as the ``updateDeployment`` path. The per-field typed code is
    still reachable for shape failures the typed input cannot encode
    (e.g. empty list — see :func:`test_deploy_create_rejects_empty_list`)."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session, version="1.0.0")
    cc = ComponentConfig(
        name="server",
        config={"identifier": {"label": {"app.kubernetes.io/name": "server-app"}}},
        application_driver_version_id=adv.id,
    )
    session.add(cc)
    await session.commit()
    driver_row = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver_row is not None

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver_row.name,
                "environmentId": str(environment.id),
                "version": "1.0.0",
                "name": "co-nonstring",
                "config": {"components": [{"name": "server", field: value}]},
            },
        },
    )
    payload = response.json()
    assert "errors" in payload, payload
    # GraphQL scalar coercion error — no typed extensions.code, just the
    # standard "String cannot represent a non string value" message naming
    # the offending value.
    message = payload["errors"][0]["message"]
    assert "String cannot represent a non string value" in message, message


@pytest.mark.asyncio
async def test_deploy_create_rejects_unknown_component(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001
) -> None:
    """The create (``deploy``) call site validates overrides identically: an
    override on an undeclared component is rejected before any reconcile
    (FR-002 covers both flows; FR-004)."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session, version="1.0.0")
    cc = ComponentConfig(
        name="server",
        config={"identifier": {"label": {"app.kubernetes.io/name": "server-app"}}},
        application_driver_version_id=adv.id,
    )
    session.add(cc)
    await session.commit()
    driver_row = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver_row is not None

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver_row.name,
                "environmentId": str(environment.id),
                "version": "1.0.0",
                "name": "co-reject",
                "config": {"components": [{"name": "ghost", "args": ["--x"]}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "UNKNOWN_COMPONENT_CONTAINER_OVERRIDE"
    assert extensions.get("component_name") == "ghost"


@pytest.mark.asyncio
async def test_deploy_create_rejects_empty_list(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,  # noqa: ARG001
) -> None:
    """The create call site rejects an empty ``args`` list (US4 Sc.2)."""
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session, version="1.0.0")
    cc = ComponentConfig(
        name="server",
        config={"identifier": {"label": {"app.kubernetes.io/name": "server-app"}}},
        application_driver_version_id=adv.id,
    )
    session.add(cc)
    await session.commit()
    driver_row = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver_row is not None

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver_row.name,
                "environmentId": str(environment.id),
                "version": "1.0.0",
                "name": "co-reject-empty",
                "config": {"components": [{"name": "server", "args": []}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" in payload, payload
    extensions = payload["errors"][0].get("extensions") or {}
    assert extensions.get("code") == "INVALID_CONTAINER_ARGS"


# ---------------------------------------------------------------------------
# US5 — orphan visibility after a (simulated) driver upgrade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphan_block_surfaced_after_upgrade(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A stored override for a component the current driver no longer declares
    surfaces with ``isOrphaned: true`` and the stored values (US5, FR-005).

    Simulates the post-upgrade state directly: the deployment's driver-component
    map is ``["db"]`` while the persisted config still carries a ``server``
    block (as it would after an upgrade renamed/removed ``server``).
    """
    deployment = await _seed_deployment_with_components(session, component_names=["db"])
    deployment.config = {
        "components": {"server": {"command": ["legacy"], "args": ["--old"]}}
    }
    session.add(deployment)
    await session.commit()

    rows = await _read_overrides(client, str(deployment.id))
    assert "server" in rows
    assert rows["server"]["isOrphaned"] is True
    assert rows["server"]["command"] == ["legacy"]
    assert rows["server"]["args"] == ["--old"]


@pytest.mark.asyncio
async def test_orphan_block_removed_via_update(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """An operator removes an orphaned block via the standard update flow and
    it disappears from the read surface (US5 Sc.4)."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(session, component_names=["db"])
    deployment_id = deployment.id
    deployment.config = {"components": {"server": {"args": ["--old"]}}}
    session.add(deployment)
    await session.commit()

    assert "server" in await _read_overrides(client, str(deployment_id))

    # Full-replacement update without the orphan block clears it.
    await _update(client, str(deployment_id), [{"name": "db"}])
    rows = await _read_overrides(client, str(deployment_id))
    assert "server" not in rows
