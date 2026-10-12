"""E2E for the cluster config update (021-cluster-config-update, research D10).

``test_cluster_update_redeploys_and_moves_dedicated_ingress`` covers User Story 1
scenarios 1 and 2 and User Story 2 scenarios 1 and 2. It updates the session
cluster's config through the SDK in four phases, on two new environments with
one ``simple-app`` each: A takes every cluster value, B sets ``ingress_class:
traefik``.

``test_edit_cluster_config_from_detail_page`` covers User Story 3 scenario 1:
it changes only the FQDN suffix in the Edit dialog of the cluster detail page.

Both tests change the cluster config that every test of ``shard_compute``
shares. The module sorts first in the shard, and each test restores the
original config and waits for the cluster to settle before it ends.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any

import kr8s
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Ingress as AsyncIngress
from kr8s.asyncio.objects import Service as AsyncService
from styrmin_sdk import StyrminClient, UpdateClusterInput
from styrmin_sdk.graphql._generated.enums import (
    ExternalDnsEndpointsType,
    ExternalUrlScheme,
    TolerationEffect,
    TolerationOperator,
)
from styrmin_sdk.graphql._generated.input_types import (
    SchedulingInput,
    TolerationInput,
)

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.helpers.ingress import (
    TaskTimes,
    deployment_tasks,
    ingress_controller_ids,
    wait_for_cluster_settled,
    wait_for_deployment_status,
    wait_for_namespace_gone,
)
from tests.e2e.pages.cluster_detail import ClusterDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page

pytestmark = [
    pytest.mark.shard_compute,
]

_REDEPLOY_TASK = "update_instance"
_ENUM_FIELDS: dict[str, type[Enum]] = {
    "external_url_scheme": ExternalUrlScheme,
    "external_dns_endpoints_type": ExternalDnsEndpointsType,
}


def _cluster_input(config: dict[str, Any]) -> UpdateClusterInput:
    """The stored cluster config as an ``UpdateClusterInput``.

    The stored config holds enum values (``http``, ``NodeExternalIP``); the input takes GraphQL names.
    """
    converted = dict(config)
    for key, enum_type in _ENUM_FIELDS.items():
        if converted.get(key) is not None:
            stored = str(converted[key]).replace("_", "").lower()
            converted[key] = next(
                member
                for member in enum_type
                if member.name.replace("_", "").lower() == stored
            )
    return UpdateClusterInput.model_validate(converted)


async def _task_ids(client: StyrminClient, deployment_id: str) -> set[str]:
    return {task.id for task in await deployment_tasks(client, deployment_id)}


async def _new_tasks(
    client: StyrminClient, deployment_id: str, known: set[str]
) -> list[TaskTimes]:
    return [
        task
        for task in await deployment_tasks(client, deployment_id)
        if task.id not in known
    ]


def _single_redeploy(tasks: list[TaskTimes], label: str) -> TaskTimes:
    redeploys = [task for task in tasks if task.type == _REDEPLOY_TASK]
    assert len(redeploys) == 1, f"{label}: expected one redeploy task, got {tasks}"
    return redeploys[0]


async def _wait_for_new_redeploy(
    client: StyrminClient, deployment_id: str, known: set[str], timeout: float = 300.0
) -> TaskTimes:
    deadline = time.time() + timeout
    while time.time() < deadline:
        tasks = await _new_tasks(client, deployment_id, known)
        if tasks:
            return _single_redeploy(tasks, f"deployment {deployment_id}")
        await asyncio.sleep(3)
    raise AssertionError(
        f"Deployment {deployment_id} got no redeploy task within {timeout}s"
    )


async def _wait_for_task_end(
    client: StyrminClient, deployment_id: str, task_id: str, timeout: float = 300.0
) -> TaskTimes:
    deadline = time.time() + timeout
    task = None
    while time.time() < deadline:
        tasks = {
            task.id: task for task in await deployment_tasks(client, deployment_id)
        }
        task = tasks[task_id]
        if task.ended_on is not None:
            assert task.status == "success", f"Task {task_id} failed: {task}"
            return task
        await asyncio.sleep(3)
    raise AssertionError(f"Task {task_id} did not end within {timeout}s: {task}")


async def _wait_for_controller_status(
    client: StyrminClient,
    environment_id: str,
    controller_id: str,
    expected: str,
    timeout: float = 300.0,
) -> None:
    deadline = time.time() + timeout
    history: dict[str, str] = {}
    while time.time() < deadline:
        history = await ingress_controller_ids(
            client, environment_id, include_deleted=True
        )
        if history.get(controller_id) == expected:
            return
        await asyncio.sleep(3)
    raise AssertionError(
        f"Ingress controller {controller_id} never reached {expected!r}: {history}"
    )


async def _wait_for_shared_ingress_class(
    kr8s_api: kr8s.asyncio.Api,
    deployment_id: str,
    ingress_class: str,
    timeout: float = 120.0,
) -> None:
    """Wait until every Ingress of the deployment uses the shared ``ingress_class``.

    Only the shared class sets ``spec.ingressClassName``; both modes set the
    ``kubernetes.io/ingress.class`` annotation, to the shared class or to the
    dedicated implementation.
    """
    namespace = f"styrmin-{deployment_id}"
    deadline = time.time() + timeout
    seen: list[tuple[Any, Any]] = []
    while time.time() < deadline:
        ingresses = [
            ingress
            async for ingress in AsyncIngress.list(namespace=namespace, api=kr8s_api)
            if isinstance(ingress, AsyncIngress)
        ]
        seen = [
            (
                ingress.spec.get("ingressClassName"),
                ingress.metadata.get("annotations", {}).get(
                    "kubernetes.io/ingress.class"
                ),
            )
            for ingress in ingresses
        ]
        if seen and all(pair == (ingress_class, ingress_class) for pair in seen):
            return
        await asyncio.sleep(3)
    raise AssertionError(
        f"Ingresses in {namespace} do not use the shared class {ingress_class!r}: "
        f"(ingressClassName, kubernetes.io/ingress.class) = {seen}"
    )


async def _traefik_service(
    kr8s_api: kr8s.asyncio.Api, environment_id: str
) -> AsyncService:
    services = [
        service
        async for service in AsyncService.list(
            namespace=kr8s.ALL,
            label_selector={
                "app.kubernetes.io/name": "traefik",
                "styrmin/environment_id": environment_id,
            },
            api=kr8s_api,
        )
        if isinstance(service, AsyncService)
    ]
    assert services, f"Traefik Service not found for environment {environment_id}"
    return services[0]


@pytest.mark.e2e
@pytest.mark.ci
@pytest.mark.api_only(
    reason="Every update goes through client.clusters.update and every check reads "
    "the SDK and kr8s; no dual-entrypoint scenario_driver method is called, so the "
    "[ui-chromium] variant would repeat the same calls without adding coverage."
)
async def test_cluster_update_redeploys_and_moves_dedicated_ingress(
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
    vcluster: dict,
):
    """Change the session cluster's config in four phases (research D10):

    1. ``dedicated_ingress`` off: both applications move to the shared class,
       and A's controller is removed only after A's application redeploy ended.
    2. ``ingress_class: nginx``: A's application is redeployed onto ``nginx``;
       B, which sets ``ingress_class: traefik``, gets no task.
    3. The original config: A's controller is created, A's application is
       redeployed only after the controller task ended, and the application
       answers over HTTP through A's controller.
    4. The same config again: no new task on either application.

    The vCluster has no shared ingress controller: no Traefik or NGINX runs
    besides the dedicated ones. So the shared-class check is on the Ingress
    resource and on the controller removal, not over HTTP.
    """
    client: StyrminClient = styrmin_resources["client"]
    cluster_id = str(styrmin_resources["cluster_id"])
    kr8s_api = await kr8s.asyncio.api(kubeconfig=vcluster["kubeconfig_path"])

    original = (await client.clusters.get(cluster_id=cluster_id)).config
    assert original.get("dedicated_ingress") is not None, original
    assert original.get("ingress_class") == "traefik", original
    original_input = _cluster_input(original)
    shared_input = original_input.model_copy(update={"dedicated_ingress": None})
    nginx_input = shared_input.model_copy(update={"ingress_class": "nginx"})

    suffix = uuid.uuid4().hex[:6]
    environment_ids: list[str] = []
    try:
        for name, config in (
            (f"cluster-update-a-{suffix}", {}),
            (f"cluster-update-b-{suffix}", {"ingress_class": "traefik"}),
        ):
            environment = await client.environments.create(
                name=name, cluster_id=cluster_id, config=config
            )
            environment_ids.append(str(environment.id))
        env_a, env_b = environment_ids

        app_ids = []
        for environment_id in environment_ids:
            task = await client.deployments.create(
                driver="simple-app", version="0.1.0", environment_id=environment_id
            )
            app_ids.append(str(task.deployment_id))
        app_a, app_b = app_ids
        for app_id in app_ids:
            await wait_for_deployment_status(client, app_id, "running")
        await wait_for_cluster_settled(client, cluster_id)
        (controller_a,) = await ingress_controller_ids(client, env_a)
        (controller_b,) = await ingress_controller_ids(client, env_b)

        # Phase 1: dedicated_ingress off moves both applications to the shared class.
        known_a = await _task_ids(client, app_a)
        known_b = await _task_ids(client, app_b)
        await client.clusters.update(shared_input, cluster_id=cluster_id)
        redeploy_a = _single_redeploy(await _new_tasks(client, app_a, known_a), "A")
        redeploy_b = _single_redeploy(await _new_tasks(client, app_b, known_b), "B")

        redeploy_a = await _wait_for_task_end(client, app_a, redeploy_a.id)
        await _wait_for_task_end(client, app_b, redeploy_b.id)
        for app_id in app_ids:
            await wait_for_deployment_status(client, app_id, "running")
            await _wait_for_shared_ingress_class(kr8s_api, app_id, "traefik")

        await _wait_for_controller_status(client, env_a, controller_a, "deleted")
        await _wait_for_controller_status(client, env_b, controller_b, "deleted")
        removals = [
            task
            for task in await deployment_tasks(client, controller_a)
            if task.type == "delete_deployment"
        ]
        assert len(removals) == 1, removals
        assert redeploy_a.ended_on is not None
        assert redeploy_a.ended_on <= removals[0].created_on, (
            f"A's controller removal was requested at {removals[0].created_on}, "
            f"before A's application redeploy ended at {redeploy_a.ended_on}"
        )
        await wait_for_namespace_gone(kr8s_api, f"styrmin-{controller_a}")

        # Phase 2: ingress_class nginx reaches A only; B overrides it.
        await wait_for_cluster_settled(client, cluster_id)
        known_a = await _task_ids(client, app_a)
        known_b = await _task_ids(client, app_b)
        await client.clusters.update(nginx_input, cluster_id=cluster_id)
        stored = (await client.clusters.get(cluster_id=cluster_id)).config
        assert stored.get("ingress_class") == "nginx", stored
        redeploy_a = _single_redeploy(await _new_tasks(client, app_a, known_a), "A")
        assert await _new_tasks(client, app_b, known_b) == []

        await _wait_for_task_end(client, app_a, redeploy_a.id)
        await wait_for_deployment_status(client, app_a, "running")
        await _wait_for_shared_ingress_class(kr8s_api, app_a, "nginx")
        assert await _new_tasks(client, app_b, known_b) == []

        # Phase 3: the original config creates A's controller before A's application moves.
        await wait_for_cluster_settled(client, cluster_id)
        known_a = await _task_ids(client, app_a)
        await client.clusters.update(original_input, cluster_id=cluster_id)
        controllers = await ingress_controller_ids(client, env_a)
        assert len(controllers) == 1, controllers
        (new_controller_a,) = controllers
        assert new_controller_a != controller_a
        assert await _new_tasks(client, app_a, known_a) == [], (
            "A's application was redeployed before its controller was ready"
        )

        (controller_task,) = [
            task
            for task in await deployment_tasks(client, new_controller_a)
            if task.type == "create_instance"
        ]
        controller_task = await _wait_for_task_end(
            client, new_controller_a, controller_task.id
        )
        redeploy_a = await _wait_for_new_redeploy(client, app_a, known_a)
        assert controller_task.ended_on is not None
        assert controller_task.ended_on <= redeploy_a.created_on, (
            f"A's application redeploy was created at {redeploy_a.created_on}, "
            f"before A's controller task ended at {controller_task.ended_on}"
        )
        await _wait_for_task_end(client, app_a, redeploy_a.id)
        await wait_for_deployment_status(client, app_a, "running")

        traefik_service = await _traefik_service(kr8s_api, env_a)
        async with _portforward(traefik_service, remote_port=8000) as local_port:
            await _wait_for_http(
                f"http://localhost:{local_port}/count",
                timeout=120.0,
                interval=3.0,
                headers={"Host": f"simple-app-{app_a}.{original['fqdn_suffix']}"},
            )

        # Phase 4: resubmitting the stored config starts no redeploy.
        await wait_for_cluster_settled(client, cluster_id)
        known_a = await _task_ids(client, app_a)
        known_b = await _task_ids(client, app_b)
        await client.clusters.update(original_input, cluster_id=cluster_id)
        await wait_for_cluster_settled(client, cluster_id)
        assert await _new_tasks(client, app_a, known_a) == []
        assert await _new_tasks(client, app_b, known_b) == []
    finally:
        await client.clusters.update(original_input, cluster_id=cluster_id)
        await wait_for_cluster_settled(client, cluster_id)
        for environment_id in environment_ids:
            await client.environments.delete(environment_id=environment_id)


# A cluster value the edit dialog does not show. No resolved config reads the
# cluster's scheduling, and a toleration only allows pods onto nodes.
_HIDDEN_SCHEDULING = SchedulingInput(
    tolerations=[
        TolerationInput(
            key="styrmin.io/cluster-edit-e2e",
            operator=TolerationOperator.EXISTS,
            effect=TolerationEffect.NO_SCHEDULE,
        )
    ]
)


@pytest.mark.e2e
@pytest.mark.ci
@pytest.mark.ui_only(
    reason="Drives the Edit dialog of the cluster detail page, which has no SDK "
    "equivalent; the SDK path is covered by "
    "test_cluster_update_redeploys_and_moves_dedicated_ingress."
)
async def test_edit_cluster_config_from_detail_page(
    styrmin_resources: dict,
    session_ui_page: Page,
) -> None:
    """Change only the FQDN suffix in the Edit dialog, signed in as the seeded admin.

    The stored config gets the new suffix and keeps every other value: the
    ones the dialog shows (``dedicated_ingress``, the storage classes,
    ``external_dns_endpoints_type``) and a ``scheduling`` value it does not
    show, which the test adds through the SDK first.
    """
    client: StyrminClient = styrmin_resources["client"]
    cluster_id = str(styrmin_resources["cluster_id"])

    original = (await client.clusters.get(cluster_id=cluster_id)).config
    for key in ("dedicated_ingress", "standard_storage", "external_dns_endpoints_type"):
        assert original.get(key) is not None, (
            f"session cluster has no {key}: {original}"
        )
    original_input = _cluster_input(original)
    new_suffix = f"edit-{uuid.uuid4().hex[:6]}.styrmin.com"

    try:
        await client.clusters.update(
            original_input.model_copy(update={"scheduling": _HIDDEN_SCHEDULING}),
            cluster_id=cluster_id,
        )
        before = (await client.clusters.get(cluster_id=cluster_id)).config
        assert before.get("scheduling"), before

        page = ClusterDetailPage(session_ui_page)
        await page.goto(cluster_id=cluster_id)
        await page.open_edit_dialog()
        await page.set_fqdn_suffix(new_suffix)
        await page.save()

        stored = (await client.clusters.get(cluster_id=cluster_id)).config
        assert stored == {**before, "fqdn_suffix": new_suffix}, (
            f"Saving the dialog changed more than the FQDN suffix.\n"
            f"before: {before}\nstored: {stored}"
        )
        await page.wait_for_section_text("Networking", new_suffix)
    finally:
        await client.clusters.update(original_input, cluster_id=cluster_id)
        await wait_for_cluster_settled(client, cluster_id)
