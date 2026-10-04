"""GraphQL ↔ DB propagation tests for per-component image overrides (018).

Constitution §V: ``ComponentConfigInput.image`` written through ``updateDeployment`` and
``deploy`` reaches ``Deployment.config["components"][name]["image"]`` through the real service
and repository layers, and ``Deployment.componentImageOverrides`` projects the stored state.
``updateDeploymentVersion`` re-validates stored, applicable overrides at the target version.
Invalid writes are rejected with typed errors naming the component, before any task (US4).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ComponentContainerPatch,
)
from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Component,
    ComponentConfig,
    Deployment,
    Task,
)
from styrmin_backend.services.component_container.patch_builder import (
    build_component_container_patches,
)
from styrmin_backend.services.context import generate_context_from_deployment_id
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

from ._queries import load_query
from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_deployment,
    seed_environment,
)

PATCHED = "registry.example/acme/simple-app-patched"


def _arm_prefect(prefect_manager_mock: Any) -> None:
    """Give the Prefect manager concrete return values so a successful reconcile dispatch
    does not leak an ``AsyncMock`` into a DB-bound column."""
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())


def _component_config(name: str, container: str | None) -> dict[str, Any]:
    return {
        "identifier": {"label": {"app.kubernetes.io/name": f"{name}-app"}},
        "container": container,
    }


async def _seed_deployment_with_components(
    session: AsyncSession, containers: dict[str, str | None]
) -> Deployment:
    """Seed a deployment whose driver declares ``containers`` (component → component
    container) and whose Component rows mirror them, as ``deploy`` copies them."""
    adv = await seed_application_driver_version(session)
    for name, container in containers.items():
        session.add(
            ComponentConfig(
                name=name,
                config=_component_config(name, container),
                application_driver_version_id=adv.id,
            )
        )
    await session.commit()
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
    await session.commit()
    return deployment


async def _update(
    client: AsyncClient, deployment_id: UUID, components: list[dict]
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {"components": components},
            },
        },
    )
    assert response.status_code == 200
    assert "errors" not in response.json(), response.json()


async def _stored_components(session: AsyncSession, deployment_id: UUID) -> dict:
    # Fresh SELECT: ``session.get`` would return the stale identity-map object.
    session.expire_all()
    row = (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()
    return (row.config or {}).get("components") or {}


async def _read_overrides(
    client: AsyncClient, deployment_id: UUID
) -> list[dict[str, Any]]:
    data = await gql(
        client,
        "get_deployment_component_image_overrides",
        {"deploymentId": str(deployment_id)},
    )
    return data["deployment"]["componentImageOverrides"]


@pytest.mark.asyncio
async def test_update_deployment_image_round_trip(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``updateDeployment`` stores ``image`` on the component block and
    ``componentImageOverrides`` projects it with the token resolved."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app", "db": "postgres"}
    )
    deployment_id = deployment.id
    reference = f"{PATCHED}:{{{{ app.version }}}}"

    await _update(client, deployment_id, [{"name": "server", "image": reference}])

    stored = await _stored_components(session, deployment_id)
    assert stored == {"server": {"image": reference}}

    assert await _read_overrides(client, deployment_id) == [
        {
            "component": "server",
            "reference": reference,
            "resolvedReference": f"{PATCHED}:1.0.0",
            "isOrphaned": False,
            "isApplicable": True,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cleared_block",
    [
        {"name": "server", "args": ["--debug"]},
        {"name": "server", "image": None, "args": ["--debug"]},
    ],
    ids=["image-omitted", "image-null"],
)
async def test_update_deployment_omitting_image_clears_it(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    cleared_block: dict[str, Any],
) -> None:
    """Full replacement: re-submitting the block without ``image`` (or with ``image: null``)
    clears the override and keeps the other slots."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app"}
    )
    deployment_id = deployment.id

    await _update(
        client,
        deployment_id,
        [{"name": "server", "image": f"{PATCHED}:0.1.0", "args": ["--debug"]}],
    )
    assert [
        row["component"] for row in await _read_overrides(client, deployment_id)
    ] == ["server"]
    await _update(client, deployment_id, [cleared_block])

    stored = await _stored_components(session, deployment_id)
    assert stored == {"server": {"args": ["--debug"]}}
    assert await _read_overrides(client, deployment_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("components", "expected_stored"),
    [
        ([], {}),
        ([{"name": "server"}], {"server": {}}),
        ([{"name": "server", "image": None}], {"server": {}}),
    ],
    ids=["block-dropped", "block-empty", "image-null"],
)
async def test_update_deployment_clearing_image_only_override(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    components: list[dict[str, Any]],
    expected_stored: dict[str, Any],
) -> None:
    """US3: clearing a block whose only slot was ``image`` leaves no stored image and
    ``componentImageOverrides`` empty, as the drawer and the SDK submit it."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app"}
    )
    deployment_id = deployment.id

    await _update(
        client, deployment_id, [{"name": "server", "image": f"{PATCHED}:0.1.0"}]
    )
    await _update(client, deployment_id, components)

    stored = await _stored_components(session, deployment_id)
    assert stored == expected_stored
    assert await _read_overrides(client, deployment_id) == []


@pytest.mark.asyncio
async def test_deploy_create_persists_image(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """``deploy(config: {components: [{name, image}]})`` stores the override on the new
    deployment exactly like the update path."""
    _arm_prefect(prefect_manager_mock)
    environment = await seed_environment(session)
    adv = await seed_application_driver_version(session, version="1.0.0")
    session.add(
        ComponentConfig(
            name="server",
            config=_component_config("server", "simple-app"),
            application_driver_version_id=adv.id,
        )
    )
    await session.commit()
    driver_row = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver_row is not None
    name = f"image-create-{uuid4().hex[:8]}"
    reference = f"{PATCHED}:{{{{ app.version }}}}"

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver_row.name,
                "environmentId": str(environment.id),
                "version": "1.0.0",
                "name": name,
                "config": {"components": [{"name": "server", "image": reference}]},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    session.expire_all()
    created = (
        await session.exec(select(Deployment).where(Deployment.name == name))
    ).one()
    assert created.config["components"]["server"]["image"] == reference

    rows = await _read_overrides(client, created.id)
    assert [(r["component"], r["resolvedReference"]) for r in rows] == [
        ("server", f"{PATCHED}:1.0.0")
    ]


@pytest.mark.asyncio
async def test_component_image_overrides_empty_when_unset(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app"}
    )
    assert await _read_overrides(client, deployment.id) == []


@pytest.mark.asyncio
async def test_component_image_overrides_projects_stored_state(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Live entries in driver order, then orphans by name. A literal tag is not substituted;
    a containerless or orphaned component is not applicable; blocks without ``image`` are
    omitted."""
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app", "worker": None, "db": "postgres"}
    )
    deployment.config = {
        "components": {
            "zombie": {"image": f"{PATCHED}:{{{{app.version}}}}"},
            "db": {"args": ["--verbose"]},
            "worker": {"image": f"{PATCHED}:{{{{ app.version }}}}-worker"},
            "server": {"image": f"{PATCHED}:0.1.0"},
            "ghost": {"image": "ghost:1"},
        }
    }
    session.add(deployment)
    await session.commit()

    data = await gql(
        client,
        "get_deployment_component_image_overrides",
        {"deploymentId": str(deployment.id)},
    )
    assert data["deployment"]["applicationVersion"] == "1.0.0"
    rows = data["deployment"]["componentImageOverrides"]
    assert rows == [
        {
            "component": "server",
            "reference": f"{PATCHED}:0.1.0",
            "resolvedReference": f"{PATCHED}:0.1.0",
            "isOrphaned": False,
            "isApplicable": True,
        },
        {
            "component": "worker",
            "reference": f"{PATCHED}:{{{{ app.version }}}}-worker",
            "resolvedReference": f"{PATCHED}:1.0.0-worker",
            "isOrphaned": False,
            "isApplicable": False,
        },
        {
            "component": "ghost",
            "reference": "ghost:1",
            "resolvedReference": "ghost:1",
            "isOrphaned": True,
            "isApplicable": False,
        },
        {
            "component": "zombie",
            "reference": f"{PATCHED}:{{{{app.version}}}}",
            "resolvedReference": f"{PATCHED}:1.0.0",
            "isOrphaned": True,
            "isApplicable": False,
        },
    ]


# ---------------------------------------------------------------------------
# US2 — updateDeploymentVersion re-validates stored, applicable overrides (T037)
# ---------------------------------------------------------------------------

# Tags disallow "+", so the token breaks only after substituting this version.
BROKEN_TARGET = "1.1.0+build"
TOKEN_REFERENCE = f"{PATCHED}:{{{{ app.version }}}}"


async def _seed_target_driver_version(
    session: AsyncSession, deployment_id: UUID, containers: dict[str, str | None]
) -> UUID:
    """Add a second version of the deployment's driver declaring ``containers``."""
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
    target_id = target.id
    for name, container in containers.items():
        session.add(
            ComponentConfig(
                name=name,
                config=_component_config(name, container),
                application_driver_version_id=target_id,
            )
        )
    await session.commit()
    return target_id


async def _store_config(
    session: AsyncSession, deployment: Deployment, config: dict[str, Any]
) -> None:
    deployment.config = config
    session.add(deployment)
    await session.commit()


async def _update_version(
    client: AsyncClient,
    deployment_id: UUID,
    version: str,
    driver_version_id: UUID | None,
) -> dict[str, Any]:
    variables: dict[str, Any] = {"deploymentId": str(deployment_id), "version": version}
    if driver_version_id is not None:
        variables["driverVersionId"] = str(driver_version_id)
    response = await client.post(
        "/graphql",
        json={"query": load_query("update_deployment_version"), "variables": variables},
    )
    assert response.status_code == 200
    return response.json()


async def _task_count(session: AsyncSession, deployment_id: UUID) -> int:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return len(rows.all())


async def _stored_row(session: AsyncSession, deployment_id: UUID) -> Deployment:
    session.expire_all()
    return (
        await session.exec(select(Deployment).where(Deployment.id == deployment_id))
    ).one()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_containers", "target_containers"),
    [
        ({"server": "simple-app"}, None),
        ({"server": None}, {"server": "simple-app"}),
    ],
    ids=["same-driver-version", "target-driver-version-declares-container"],
)
async def test_update_deployment_version_rejects_reference_broken_by_substitution(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    current_containers: dict[str, str | None],
    target_containers: dict[str, str | None] | None,
) -> None:
    """A stored override applicable in the target driver version that resolves to an invalid
    reference at the target application version rejects the upgrade before any task."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(session, current_containers)
    deployment_id = deployment.id
    driver_version_before = deployment.application_driver_version_id
    config = {"components": {"server": {"image": TOKEN_REFERENCE}}}
    await _store_config(session, deployment, config)
    target_id = (
        await _seed_target_driver_version(session, deployment_id, target_containers)
        if target_containers is not None
        else None
    )

    payload = await _update_version(client, deployment_id, BROKEN_TARGET, target_id)

    assert "errors" in payload, payload
    error = payload["errors"][0]
    extensions = error.get("extensions") or {}
    assert extensions.get("code") == "INVALID_IMAGE_REFERENCE", extensions
    assert extensions.get("component_name") == "server", extensions
    assert extensions.get("reference") == TOKEN_REFERENCE, extensions
    assert extensions.get("reason") == "after_substitution", extensions
    assert extensions.get("application_version") == BROKEN_TARGET, extensions
    assert "'server'" in error["message"]

    prefect_manager_mock.run_action.assert_not_awaited()
    assert await _task_count(session, deployment_id) == 0
    stored = await _stored_row(session, deployment_id)
    assert stored.application_version == "1.0.0"
    assert stored.application_driver_version_id == driver_version_before
    assert stored.config == config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_containers", "config", "target_containers"),
    [
        (
            {"server": "simple-app", "worker": None},
            {
                "components": {
                    "server": {"image": f"{PATCHED}:0.1.0"},
                    "worker": {"image": TOKEN_REFERENCE},
                }
            },
            None,
        ),
        (
            {"server": "simple-app"},
            {"components": {"server": {"image": TOKEN_REFERENCE}}},
            {"server": None},
        ),
        (
            {"server": "simple-app"},
            {"components": {"server": {"image": TOKEN_REFERENCE}}},
            {"api": "api"},
        ),
    ],
    ids=[
        "containerless-component",
        "target-driver-version-drops-container",
        "target-driver-version-drops-component",
    ],
)
async def test_update_deployment_version_ignores_non_applicable_override(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    current_containers: dict[str, str | None],
    config: dict[str, Any],
    target_containers: dict[str, str | None] | None,
) -> None:
    """An override that is not applicable in the target driver version (containerless or
    orphaned component) is never rendered, so it does not block the upgrade."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(session, current_containers)
    deployment_id = deployment.id
    await _store_config(session, deployment, config)
    target_id = (
        await _seed_target_driver_version(session, deployment_id, target_containers)
        if target_containers is not None
        else None
    )

    payload = await _update_version(client, deployment_id, BROKEN_TARGET, target_id)

    assert "errors" not in payload, payload
    assert await _task_count(session, deployment_id) == 1
    stored = await _stored_row(session, deployment_id)
    assert stored.application_version == BROKEN_TARGET
    assert stored.config == config


# ---------------------------------------------------------------------------
# US4 — write-time validation on deploy and updateDeployment (T055)
# ---------------------------------------------------------------------------

INVALID_REFERENCE_CASES = [
    ("App:1", "1.0.0", "grammar", None),
    (PATCHED, "1.0.0", "missing_tag_or_digest", None),
    (f"{PATCHED}:{{{{ app.name }}}}", "1.0.0", "template_expression", None),
    (TOKEN_REFERENCE, BROKEN_TARGET, "after_substitution", BROKEN_TARGET),
]
INVALID_REFERENCE_IDS = [
    "grammar",
    "missing-tag-or-digest",
    "template-expression",
    "after-substitution",
]


async def _post_update(
    client: AsyncClient, deployment_id: UUID, components: list[dict]
) -> dict[str, Any]:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment_config"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {"components": components},
            },
        },
    )
    assert response.status_code == 200
    return response.json()


async def _seed_deploy_driver(
    session: AsyncSession, containers: dict[str, str | None]
) -> tuple[str, UUID]:
    """Seed an environment and a driver version declaring ``containers``; return the
    driver name and the environment id for a ``deploy`` call."""
    environment = await seed_environment(session)
    environment_id = environment.id
    adv = await seed_application_driver_version(session, version="1.0.0")
    for name, container in containers.items():
        session.add(
            ComponentConfig(
                name=name,
                config=_component_config(name, container),
                application_driver_version_id=adv.id,
            )
        )
    await session.commit()
    driver_row = await session.get(ApplicationDriver, adv.application_driver_id)
    assert driver_row is not None
    return driver_row.name, environment_id


async def _post_deploy(
    client: AsyncClient,
    driver_name: str,
    environment_id: UUID,
    components: list[dict],
    *,
    version: str = "1.0.0",
) -> tuple[str, dict[str, Any]]:
    name = f"image-deploy-{uuid4().hex[:8]}"
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("deploy_with_config"),
            "variables": {
                "driver": driver_name,
                "environmentId": str(environment_id),
                "version": version,
                "name": name,
                "config": {"components": components},
            },
        },
    )
    assert response.status_code == 200
    return name, response.json()


def _assert_error(payload: dict[str, Any], code: str, **metadata: Any) -> str:
    """Assert the first error carries ``code`` and ``metadata``; return its message."""
    assert "errors" in payload, payload
    error = payload["errors"][0]
    extensions = error.get("extensions") or {}
    assert extensions.get("code") == code, extensions
    for key, value in metadata.items():
        assert extensions.get(key) == value, extensions
    return error["message"]


async def _assert_update_rejected_without_task(
    session: AsyncSession,
    prefect_manager_mock: Any,
    deployment_id: UUID,
    stored_before: dict | None,
) -> None:
    prefect_manager_mock.run_action.assert_not_awaited()
    assert await _task_count(session, deployment_id) == 0
    assert (await _stored_row(session, deployment_id)).config == stored_before


async def _assert_deploy_rejected_without_task(
    session: AsyncSession, prefect_manager_mock: Any, name: str
) -> None:
    prefect_manager_mock.run_action.assert_not_awaited()
    session.expire_all()
    created = await session.exec(select(Deployment).where(Deployment.name == name))
    assert created.all() == []
    assert (await session.exec(select(Task))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference", "application_version", "reason", "reported_version"),
    INVALID_REFERENCE_CASES,
    ids=INVALID_REFERENCE_IDS,
)
async def test_update_deployment_rejects_invalid_reference(  # noqa: PLR0913
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    reference: str,
    application_version: str,
    reason: str,
    reported_version: str | None,
) -> None:
    """Every ``INVALID_IMAGE_REFERENCE`` reason names the component, with the token checked
    against the deployment's current application version, and starts nothing."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app"}
    )
    deployment_id = deployment.id
    deployment.application_version = application_version
    session.add(deployment)
    await session.commit()

    payload = await _post_update(
        client, deployment_id, [{"name": "server", "image": reference}]
    )

    message = _assert_error(
        payload,
        "INVALID_IMAGE_REFERENCE",
        component_name="server",
        reference=reference,
        reason=reason,
        application_version=reported_version,
    )
    assert "'server'" in message
    await _assert_update_rejected_without_task(
        session, prefect_manager_mock, deployment_id, None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference", "application_version", "reason", "reported_version"),
    INVALID_REFERENCE_CASES,
    ids=INVALID_REFERENCE_IDS,
)
async def test_deploy_rejects_invalid_reference(  # noqa: PLR0913
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    reference: str,
    application_version: str,
    reason: str,
    reported_version: str | None,
) -> None:
    """``deploy`` checks the token against the requested application version and creates
    neither a deployment nor a task on rejection."""
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(
        session, {"server": "simple-app"}
    )

    name, payload = await _post_deploy(
        client,
        driver_name,
        environment_id,
        [{"name": "server", "image": reference}],
        version=application_version,
    )

    message = _assert_error(
        payload,
        "INVALID_IMAGE_REFERENCE",
        component_name="server",
        reference=reference,
        reason=reason,
        application_version=reported_version,
    )
    assert "'server'" in message
    await _assert_deploy_rejected_without_task(session, prefect_manager_mock, name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference", [f"{PATCHED}:0.1.0", "App"], ids=["valid", "invalid"]
)
async def test_update_deployment_rejects_unknown_component(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    reference: str,
) -> None:
    """The unknown-component check runs before the reference check."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app", "worker": None}
    )
    deployment_id = deployment.id

    payload = await _post_update(
        client, deployment_id, [{"name": "ghost", "image": reference}]
    )

    message = _assert_error(
        payload,
        "UNKNOWN_COMPONENT_IMAGE_OVERRIDE",
        component_name="ghost",
        known_components=["server", "worker"],
    )
    assert "'ghost'" in message
    await _assert_update_rejected_without_task(
        session, prefect_manager_mock, deployment_id, None
    )


@pytest.mark.asyncio
async def test_deploy_rejects_unknown_component(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(
        session, {"server": "simple-app", "worker": None}
    )

    name, payload = await _post_deploy(
        client,
        driver_name,
        environment_id,
        [{"name": "ghost", "image": f"{PATCHED}:0.1.0"}],
    )

    _assert_error(
        payload,
        "UNKNOWN_COMPONENT_IMAGE_OVERRIDE",
        component_name="ghost",
        known_components=["server", "worker"],
    )
    await _assert_deploy_rejected_without_task(session, prefect_manager_mock, name)


# ``server`` declares a component container, ``worker`` declares none.
STORED_WORKER_IMAGE = f"{PATCHED}:0.1.0"


async def _seed_containerless_override(
    session: AsyncSession, stored_worker_image: str | None
) -> tuple[UUID, dict | None]:
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app", "worker": None}
    )
    config = (
        {"components": {"worker": {"image": stored_worker_image}}}
        if stored_worker_image is not None
        else None
    )
    if config is not None:
        await _store_config(session, deployment, config)
    return deployment.id, config


def _assert_container_not_declared(payload: dict[str, Any]) -> None:
    message = _assert_error(
        payload,
        "COMPONENT_CONTAINER_NOT_DECLARED",
        component_name="worker",
        components_with_container=["server"],
        override="image",
    )
    assert message.startswith("Image override targets component 'worker'"), message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_worker_image", "submitted"),
    [
        (None, f"{PATCHED}:0.2.0"),
        (STORED_WORKER_IMAGE, f"{PATCHED}:0.2.0"),
        (STORED_WORKER_IMAGE, TOKEN_REFERENCE),
    ],
    ids=["add", "change", "change-to-token"],
)
async def test_update_deployment_rejects_image_on_containerless_component(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    stored_worker_image: str | None,
    submitted: str,
) -> None:
    _arm_prefect(prefect_manager_mock)
    deployment_id, stored_before = await _seed_containerless_override(
        session, stored_worker_image
    )

    payload = await _post_update(
        client, deployment_id, [{"name": "worker", "image": submitted}]
    )

    _assert_container_not_declared(payload)
    await _assert_update_rejected_without_task(
        session, prefect_manager_mock, deployment_id, stored_before
    )


@pytest.mark.asyncio
async def test_deploy_rejects_image_on_containerless_component(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A new deployment has no stored config: every image is an addition."""
    _arm_prefect(prefect_manager_mock)
    driver_name, environment_id = await _seed_deploy_driver(
        session, {"server": "simple-app", "worker": None}
    )

    name, payload = await _post_deploy(
        client,
        driver_name,
        environment_id,
        [{"name": "worker", "image": f"{PATCHED}:0.1.0"}],
    )

    _assert_container_not_declared(payload)
    await _assert_deploy_rejected_without_task(session, prefect_manager_mock, name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("submitted_block", "expected_worker"),
    [
        ({"name": "worker"}, {}),
        ({"name": "worker", "image": None}, {}),
        (
            {"name": "worker", "image": STORED_WORKER_IMAGE},
            {"image": STORED_WORKER_IMAGE},
        ),
    ],
    ids=["remove-omitted", "remove-null", "unchanged"],
)
async def test_update_deployment_accepts_removal_or_unchanged_on_containerless_component(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
    submitted_block: dict[str, Any],
    expected_worker: dict[str, Any],
) -> None:
    """A stored override on a containerless component can be removed or re-submitted as is."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, _ = await _seed_containerless_override(session, STORED_WORKER_IMAGE)

    payload = await _post_update(client, deployment_id, [submitted_block])

    assert "errors" not in payload, payload
    assert await _stored_components(session, deployment_id) == {
        "worker": expected_worker
    }


@pytest.mark.asyncio
async def test_update_deployment_env_vars_on_containerless_component_keep_env_error(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """Env vars and an unchanged image on a containerless component report the env-var slot."""
    _arm_prefect(prefect_manager_mock)
    deployment_id, stored_before = await _seed_containerless_override(
        session, STORED_WORKER_IMAGE
    )

    payload = await _post_update(
        client,
        deployment_id,
        [
            {
                "name": "worker",
                "image": STORED_WORKER_IMAGE,
                "envVars": [{"name": "A", "value": "1"}],
            }
        ],
    )

    message = _assert_error(
        payload,
        "COMPONENT_CONTAINER_NOT_DECLARED",
        component_name="worker",
        override="env_vars",
    )
    assert message.startswith("Environment variables target component 'worker'")
    await _assert_update_rejected_without_task(
        session, prefect_manager_mock, deployment_id, stored_before
    )


# ---------------------------------------------------------------------------
# US4 — an override stranded by a driver upgrade (T058)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_stranded_by_driver_upgrade_is_kept_but_not_rendered(
    client: AsyncClient, session: AsyncSession, prefect_manager_mock
) -> None:
    """A driver version that drops ``server``'s component container keeps its override,
    reads it back as not applicable, and renders no patch for it."""
    _arm_prefect(prefect_manager_mock)
    deployment = await _seed_deployment_with_components(
        session, {"server": "simple-app", "db": "postgres"}
    )
    deployment_id = deployment.id
    db_image = f"{PATCHED}-db:0.1.0"
    await _update(
        client,
        deployment_id,
        [
            {"name": "server", "image": TOKEN_REFERENCE},
            {"name": "db", "image": db_image},
        ],
    )
    target_id = await _seed_target_driver_version(
        session, deployment_id, {"server": None, "db": "postgres"}
    )

    payload = await _update_version(client, deployment_id, "1.0.0", target_id)

    assert "errors" not in payload, payload
    stored = await _stored_row(session, deployment_id)
    assert stored.application_driver_version_id == target_id
    assert stored.config["components"]["server"] == {"image": TOKEN_REFERENCE}
    rows = await _read_overrides(client, deployment_id)
    assert [
        (row["component"], row["isOrphaned"], row["isApplicable"]) for row in rows
    ] == [("server", False, False), ("db", False, True)]

    context = await generate_context_from_deployment_id(
        deployment_id, SqlModelUnitOfWork(session=session)
    )
    assert context.components is not None
    assert context.components.root["server"].image_override is not None
    patches = build_component_container_patches(context)
    guards = [
        tp.patch for tp in patches if isinstance(tp.patch, ComponentContainerPatch)
    ]
    assert {(guard.component, guard.image) for guard in guards} == {("db", db_image)}
