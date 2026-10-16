"""E2E for the cluster config update (021-cluster-config-update, research D10).

``test_cluster_update_redeploys_and_moves_dedicated_ingress`` covers User Story 1
scenarios 1 and 2 and User Story 2 scenarios 1 and 2. It updates the session
cluster's config through the SDK in four phases, on two new environments with
one ``simple-app`` each: A takes every cluster value, B sets ``ingress_class:
traefik``. Before phase 3, A gets a second ``simple-app``, C, that sets its own
``dedicated_ingress`` (#453).

``test_edit_cluster_config_from_detail_page`` covers User Story 3 scenario 1:
it changes only the FQDN suffix in the Edit dialog of the cluster detail page.

Both tests change the cluster config that every test of ``shard_compute``
shares. They carry ``changes_cluster_config``, which the e2e conftest runs
before every other test of the session, and each test restores the original
config and waits for the cluster to settle before it ends.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

import kr8s
import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Ingress as AsyncIngress
from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.input_types import (
    DedicatedIngressInput,
    DeploymentConfigInput,
    IngressServiceConfigInput,
)
from styrmin_sdk.models import IngressControllerAction

from tests.e2e.conftest import _portforward, _wait_for_http
from tests.e2e.helpers.ingress import (
    deployment_tasks,
    ingress_controller_ids,
    new_tasks,
    single_redeploy,
    task_ids,
    traefik_service,
    wait_for_cluster_settled,
    wait_for_controller_status,
    wait_for_deployment_status,
    wait_for_namespace_gone,
    wait_for_new_redeploy,
    wait_for_task_end,
)
from tests.e2e.pages.cluster_detail import ClusterDetailPage

if TYPE_CHECKING:
    from playwright.async_api import Page
    from styrmin_sdk.models import ClusterUpdateResult

pytestmark = [
    pytest.mark.shard_compute,
    pytest.mark.changes_cluster_config,
]


def _deployment_ids(entries: list[Any]) -> set[str]:
    return {str(entry.deployment_id) for entry in entries}


def _assert_no_failure(result: ClusterUpdateResult) -> None:
    failed_controllers = [c for c in result.ingress_controllers if c.failed]
    assert not (
        result.failed_to_start or result.failed_environments or failed_controllers
    ), result


async def _restore(
    client: StyrminClient, cluster_id: str, original: dict[str, Any]
) -> None:
    """Restore the original cluster config and wait for the cluster to settle."""
    await client.clusters.update(original, cluster_id=cluster_id)
    await wait_for_cluster_settled(client, cluster_id)


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
       answers over HTTP through A's controller. C, which sets its own
       ``dedicated_ingress``, is redeployed at once (#453).
    4. The same config again: no new task on any application.

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
    shared = {
        key: value for key, value in original.items() if key != "dedicated_ingress"
    }
    nginx = {**shared, "ingress_class": "nginx"}

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
        known_a = await task_ids(client, app_a)
        known_b = await task_ids(client, app_b)
        result = await client.clusters.update(shared, cluster_id=cluster_id)
        assert {app_a, app_b} <= _deployment_ids(result.redeployed), result
        assert {env_a, env_b} <= {
            str(controller.environment_id)
            for controller in result.ingress_controllers
            if controller.action == IngressControllerAction.REMOVE
        }, result
        redeploy_a = single_redeploy(await new_tasks(client, app_a, known_a), "A")
        redeploy_b = single_redeploy(await new_tasks(client, app_b, known_b), "B")
        assert {str(entry.task_id) for entry in result.redeployed} >= {
            redeploy_a.id,
            redeploy_b.id,
        }, result

        redeploy_a = await wait_for_task_end(client, app_a, redeploy_a.id)
        await wait_for_task_end(client, app_b, redeploy_b.id)
        for app_id in app_ids:
            await wait_for_deployment_status(client, app_id, "running")
            await _wait_for_shared_ingress_class(kr8s_api, app_id, "traefik")

        await wait_for_controller_status(client, env_a, controller_a, "deleted")
        await wait_for_controller_status(client, env_b, controller_b, "deleted")
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
        known_a = await task_ids(client, app_a)
        known_b = await task_ids(client, app_b)
        preview = await client.clusters.update(
            nginx, cluster_id=cluster_id, dry_run=True
        )
        assert preview.dry_run
        assert app_a in _deployment_ids(preview.redeployed), preview
        assert app_b not in _deployment_ids(preview.redeployed), preview
        assert (await client.clusters.get(cluster_id=cluster_id)).config == shared
        assert await new_tasks(client, app_a, known_a) == []

        result = await client.clusters.update(nginx, cluster_id=cluster_id)
        _assert_no_failure(result)
        stored = (await client.clusters.get(cluster_id=cluster_id)).config
        assert stored.get("ingress_class") == "nginx", stored
        redeploy_a = single_redeploy(await new_tasks(client, app_a, known_a), "A")
        assert await new_tasks(client, app_b, known_b) == []

        await wait_for_task_end(client, app_a, redeploy_a.id)
        await wait_for_deployment_status(client, app_a, "running")
        await _wait_for_shared_ingress_class(kr8s_api, app_a, "nginx")
        assert await new_tasks(client, app_b, known_b) == []

        # C keeps its own dedicated_ingress, so phase 3 does not move it onto A's controller (#453).
        task = await client.deployments.create(
            driver="simple-app",
            version="0.1.0",
            environment_id=env_a,
            service_name_overrides=[
                {"driverServiceName": "simple-app", "overrideName": "simple-app-c"}
            ],
            config=DeploymentConfigInput(
                dedicated_ingress=DedicatedIngressInput(
                    service=IngressServiceConfigInput(type="NodePort")
                )
            ),
        )
        app_c = str(task.deployment_id)
        await wait_for_deployment_status(client, app_c, "running")

        # Phase 3: the original config creates A's controller before A's application moves.
        await wait_for_cluster_settled(client, cluster_id)
        known_a = await task_ids(client, app_a)
        known_c = await task_ids(client, app_c)
        result = await client.clusters.update(original, cluster_id=cluster_id)
        _assert_no_failure(result)
        assert app_a in _deployment_ids(result.waiting_for_ingress), result
        assert app_c in _deployment_ids(result.redeployed), result
        assert app_c not in _deployment_ids(result.waiting_for_ingress), result
        redeploy_c = single_redeploy(await new_tasks(client, app_c, known_c), "C")
        assert (env_a, IngressControllerAction.CREATE) in {
            (str(controller.environment_id), controller.action)
            for controller in result.ingress_controllers
        }, result
        controllers = await ingress_controller_ids(client, env_a)
        assert len(controllers) == 1, controllers
        (new_controller_a,) = controllers
        assert new_controller_a != controller_a
        assert await new_tasks(client, app_a, known_a) == [], (
            "A's application was redeployed before its controller was ready"
        )

        (controller_task,) = [
            task
            for task in await deployment_tasks(client, new_controller_a)
            if task.type == "create_instance"
        ]
        controller_task = await wait_for_task_end(
            client, new_controller_a, controller_task.id
        )
        redeploy_a = await wait_for_new_redeploy(client, app_a, known_a)
        assert controller_task.ended_on is not None
        assert controller_task.ended_on <= redeploy_a.created_on, (
            f"A's application redeploy was created at {redeploy_a.created_on}, "
            f"before A's controller task ended at {controller_task.ended_on}"
        )
        await wait_for_task_end(client, app_a, redeploy_a.id)
        await wait_for_deployment_status(client, app_a, "running")
        await wait_for_task_end(client, app_c, redeploy_c.id)
        await wait_for_deployment_status(client, app_c, "running")

        service = await traefik_service(kr8s_api, env_a)
        async with _portforward(service, remote_port=8000) as local_port:
            await _wait_for_http(
                f"http://localhost:{local_port}/count",
                timeout=120.0,
                interval=3.0,
                headers={"Host": f"simple-app-{app_a}.{original['fqdn_suffix']}"},
            )

        # Phase 4: resubmitting the stored config starts no redeploy.
        await wait_for_cluster_settled(client, cluster_id)
        known_a = await task_ids(client, app_a)
        known_b = await task_ids(client, app_b)
        known_c = await task_ids(client, app_c)
        result = await client.clusters.update(original, cluster_id=cluster_id)
        _assert_no_failure(result)
        assert not {app_a, app_b, app_c} & _deployment_ids(result.redeployed), result
        await wait_for_cluster_settled(client, cluster_id)
        assert await new_tasks(client, app_a, known_a) == []
        assert await new_tasks(client, app_b, known_b) == []
        assert await new_tasks(client, app_c, known_c) == []
    finally:
        try:
            await _restore(client, cluster_id, original)
        finally:
            for environment_id in environment_ids:
                await client.environments.delete(environment_id=environment_id)


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
    ``external_dns_endpoints_type``) and a ``backup_ttl`` value it does not
    show, which the test adds through the SDK first.
    """
    client: StyrminClient = styrmin_resources["client"]
    cluster_id = str(styrmin_resources["cluster_id"])

    original = (await client.clusters.get(cluster_id=cluster_id)).config
    for key in ("dedicated_ingress", "standard_storage", "external_dns_endpoints_type"):
        assert original.get(key) is not None, (
            f"session cluster has no {key}: {original}"
        )
    new_suffix = f"edit-{uuid.uuid4().hex[:6]}.styrmin.com"
    hidden_ttl = "2160h" if original.get("backup_ttl") == "1440h" else "1440h"

    try:
        result = await client.clusters.update(
            {**original, "backup_ttl": hidden_ttl}, cluster_id=cluster_id
        )
        _assert_no_failure(result)
        await wait_for_cluster_settled(client, cluster_id)
        before = (await client.clusters.get(cluster_id=cluster_id)).config
        assert before.get("backup_ttl") == hidden_ttl, before

        page = ClusterDetailPage(session_ui_page)
        await page.goto(cluster_id=cluster_id)
        await page.open_edit_dialog()
        await page.set_fqdn_suffix(new_suffix)
        review = await page.review()
        assert "FQDN suffix" in review and new_suffix in review, review
        assert "Application URLs change" in review, review
        saved = await page.save()
        assert "The configuration was saved" in saved, saved
        assert "Save again to retry them" not in saved, saved

        stored = (await client.clusters.get(cluster_id=cluster_id)).config
        assert stored == {**before, "fqdn_suffix": new_suffix}, (
            f"Saving the dialog changed more than the FQDN suffix.\n"
            f"before: {before}\nstored: {stored}"
        )
        await page.wait_for_section_text("Networking", new_suffix)
    finally:
        await _restore(client, cluster_id, original)
